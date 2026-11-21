"""Optional exact recording segments; an index never creates a media grant."""

from django.apps import apps
from django.conf import settings

from apps.casework import services as cases
from apps.timed_citations.rights import TimedMediaRights

from .sources import _document


def _configuration():
    installed = apps.is_installed("apps.public_answer_media")
    enabled = getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", None)
    authority = getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY", None)
    rights = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    epochs, available = (), False
    if installed and enabled is True:
        from apps.public_answer_media.authority import AnswerMediaAuthority

        if isinstance(authority, AnswerMediaAuthority) and isinstance(rights, TimedMediaRights):
            try:
                epochs = (authority.projection_epoch(), rights.media_projection_epoch())
                available = all(
                    type(value) is str and 1 <= len(value) <= 131072 for value in epochs
                )
            except Exception:
                epochs = ()
    # Strong references and identity pins defeat value-equal replacement and ID reuse.
    return available, (
        installed,
        type(enabled),
        enabled,
        id(authority),
        authority,
        id(rights),
        rights,
        epochs,
    )


class RecordingSources:
    def __init__(self, case_ids, provider, actor):
        self.provider, self.actor = provider, actor
        self.configuration = _configuration()
        self.snapshots = {}
        if self.configuration[0]:
            from apps.public_answer_media import services as recordings

            for case_id in case_ids:
                self.snapshots[str(case_id)] = recordings.snapshot(case_id, provider)

    def read(self, case):
        if not self.configuration[0]:
            return []
        from apps.public_answer_media import services as recordings
        from apps.public_answer_media.models import RecordingTranscript

        initial = self.snapshots[str(case.pk)]
        with recordings.search_projection(
            case_id=str(case.pk),
            subject_id=self.actor.subject_id,
            provider=self.provider,
            synthetic_fixtures_only=True,
        ) as projection:
            rows = list(projection["rows"])
            consumed = projection["snapshot"]
        # Retain the original pre-callback row/epoch snapshot. Only consumed
        # bytes and deadlines may be accumulated from a later child projection.
        initial.files.update(consumed.files)
        initial.deadlines.extend(consumed.deadlines)
        recordings.assert_projection_state(initial)
        result = []
        for row in rows:
            pin = dict(row["pin"])
            version = RecordingTranscript.objects.get(
                pk=pin["transcript_id"], case=case, digest=pin["transcript_digest"]
            )
            expected_url = f"/casework/staff/recording-transcripts/{version.pk}/segments/{pin['segment_index']}/"
            if row["segment_url"] != expected_url or pin.pop("case_id") != str(case.pk):
                raise cases.CaseConflict("search_recording_source_changed")
            result.append(
                _document(
                    case,
                    "RECORDING_TRANSCRIPT",
                    version.pk,
                    row["text"],
                    version.digest,
                    version.number,
                    row["label"],
                    **pin,
                )
            )
        return result

    def verify_bytes(self):
        if self.configuration[0]:
            from apps.public_answer_media import services as recordings

            # A later case's storage callback must not revoke an earlier case
            # after its final check. Finish every byte read before the pure pass.
            for pin in self.snapshots.values():
                recordings.assert_snapshot(pin)

    def final_pins(self):
        if self.configuration[0]:
            from apps.public_answer_media import services as recordings

            for pin in self.snapshots.values():
                recordings.assert_projection_state(pin)
        if _configuration() != self.configuration:
            raise cases.CaseConflict("search_recording_policy_changed")

    def finish(self):
        self.verify_bytes()
        self.final_pins()
