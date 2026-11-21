"""Actual organizer editorial transcripts; canonical authors and meaning stay MUFTI."""

import uuid
from contextlib import contextmanager
from hashlib import sha256

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.public_answer_media import services as recording
from apps.public_answer_media.boundaries import Boundary, assert_projection_state
from apps.public_answer_media.models import RecordingTranscript

from . import answer_sources
from .boundary import scope

ACTION_MAP = {
    "READ_TRANSCRIPT": "READ_RECORDING_TRANSCRIPT",
    "EDIT_TRANSCRIPT": "EDIT_RECORDING_TRANSCRIPT",
    "REVIEW_TRANSCRIPT": "REVIEW_RECORDING_TRANSCRIPT",
    "REVIEW_MEANING": "APPROVE_TRANSCRIPT_MEANING",
    "WITHDRAW_TRANSCRIPT": "WITHDRAW_RECORDING_TRANSCRIPT",
}


def resource(case, part, transcript=None):
    result = {
        "kind": "CASE_RECORDING_TRANSCRIPT" if transcript else "CASE_RECORDING_SOURCE",
        "case_id": str(case.pk),
        "part_id": str(part.pk),
        "part_sha256": part.sha256,
    }
    if transcript is not None:
        result.update(transcript_id=str(transcript.pk), transcript_digest=transcript.digest)
    return result


class TranscriptBridge(Boundary):
    def __init__(self, case, guard):
        self.operational = guard
        super().__init__(case, guard.provider)
        self.editorial_actor(guard.actor.subject_id)
        guard.adapters.append(self)

    def _resource(self, value):
        if value.get("edition_id") or value.get("edition_digest"):
            raise cases.CaseConflict("operational_transcript_action_unavailable")
        part = AnswerPart.objects.filter(
            pk=cases._uuid(value.get("part_id")), manifest__answer__case=self.case, kind="AUDIO"
        ).first()
        if part is None or part.sha256 != value.get("part_sha256"):
            raise cases.CaseConflict("operational_transcript_source_changed")
        row = None
        if value.get("transcript_id"):
            row = RecordingTranscript.objects.filter(
                pk=cases._uuid(value["transcript_id"]), case=self.case, part=part
            ).first()
            if row is None or row.digest != value.get("transcript_digest"):
                raise cases.CaseConflict("operational_transcript_changed")
        return resource(self.case, part, row)

    def allowed(self, actor, action, value, *, required=False):
        if action not in ACTION_MAP or actor.subject_id != self.operational.actor.subject_id:
            raise cases.CaseConflict("operational_transcript_action_unavailable")
        if action == "REVIEW_MEANING" and actor.role != "MUFTI":
            if required:
                raise cases.CaseConflict("recording_meaning_mufti_required")
            return False
        if not self.operational.permit_resource(
            self.case, ACTION_MAP[action], self._resource(value), required=required
        ):
            return False
        try:
            super().permit(actor, action, value)
        except cases.CaseConflict as exc:
            if str(exc) == "recording_action_denied" and not required:
                # Rejected candidate permissions are pinned by the policy epoch,
                # and must not be replayed as required grants in callbacks().
                self.permissions.pop()
                return False
            raise
        return True

    def permit(self, actor, action, value):
        return self.allowed(actor, action, value, required=True)

    def external_reads(self):
        # Complete all storage callbacks before Guard's pure final pins.
        for part in self.pin.files.values():
            raw = media.raw_for_part(part)
            if len(raw) != part.size or sha256(raw).hexdigest() != part.sha256:
                raise cases.CaseConflict("recording_original_changed")

    def final_pins(self):
        assert_projection_state(self.pin)

    def account_for_append(self, row):
        # Outer exact-one-row accounting rejects unrelated callback writes before
        # the existing media reader adopts the intentional derivative revision.
        self.operational.account_for_append(row)
        self.freeze_after_write()


def available(case, guard):
    return guard.transcript_feature and guard.permit(
        case, "READ_TRANSCRIPT_EDITOR", "transcript_editor"
    )


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.transcript_feature:
        raise cases.CaseConflict("operational_transcripts_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_transcripts_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    guard.permit(case, "READ_TRANSCRIPT_EDITOR", "transcript_editor", required=True)
    cases._verify(case)
    return case


def _part(case, identifier, expected_hash):
    row = AnswerPart.objects.filter(
        pk=cases._uuid(identifier), manifest__answer__case=case, kind="AUDIO"
    ).first()
    if row is None or row.sha256 != expected_hash:
        raise cases.CaseConflict("operational_transcript_source_changed")
    return row


def _options(bridge, actor, row, actions):
    proposed = []
    if not actions and (row.provider_id, row.subject_id) != (
        bridge.provider.provider_id,
        actor.subject_id,
    ):
        proposed.append("APPROVE_MEANING" if row.change_kind == "MEANING_REVIEW" else "REVIEW")
    if not any(event.action == "WITHDRAW" for event in actions):
        proposed.append("WITHDRAW")
    return [
        command
        for command in proposed
        if bridge.allowed(
            actor,
            {
                "REVIEW": "REVIEW_TRANSCRIPT",
                "APPROVE_MEANING": "REVIEW_MEANING",
                "WITHDRAW": "WITHDRAW_TRANSCRIPT",
            }[command],
            recording._resource(row.part, row),
        )
    ]


def _projection(case, guard, bridge, *, saved=False):
    parts, transcripts = [], []
    for candidate in AnswerPart.objects.filter(
        manifest__answer_id=case.approved_answer_id, kind="AUDIO"
    ).order_by("ordinal"):
        if not bridge.allowed(guard.actor, "READ_TRANSCRIPT", recording._resource(candidate)):
            continue
        part, pins, _ = recording._source(bridge, guard.actor, candidate.pk)
        history = list(RecordingTranscript.objects.filter(part=part).order_by("number"))
        if len(history) > 64:
            raise cases.CaseConflict("operational_transcript_history_bound")
        visible = []
        for row in history:
            if not bridge.allowed(guard.actor, "READ_TRANSCRIPT", recording._resource(part, row)):
                continue
            row, _, _, actions = recording._transcript(bridge, guard.actor, row.pk)
            visible.append(row)
            dto = recording._transcript_dto(row, actions)
            dto.pop("audio_url")
            dto.update(
                part_sha256=part.sha256,
                options=_options(bridge, guard.actor, row, actions),
            )
            transcripts.append(dto)
        latest = visible[-1] if visible else None
        latest_readable = not history or (latest is not None and latest.pk == history[-1].pk)
        inputs = []
        for index in range(recording.MAX_SEGMENTS):
            segment = latest.segments[index] if latest and index < len(latest.segments) else None
            inputs.append(
                {
                    "index": index,
                    "quote": latest.text[segment["char_start"] : segment["char_end"]]
                    if segment
                    else "",
                    "start_ms": segment["start_ms"] if segment else "",
                    "end_ms": segment["end_ms"] if segment else "",
                }
            )
        parts.append(
            {
                "id": str(part.pk),
                "sha256": part.sha256,
                "ordinal": part.ordinal,
                "duration_ms": pins["duration_ms"],
                "version": latest.number if latest else 0,
                "text": latest.text if latest else "",
                "segment_inputs": inputs,
                "can_edit": latest_readable
                and bridge.allowed(guard.actor, "EDIT_TRANSCRIPT", recording._resource(part)),
                "can_audio": guard.permit_resource(
                    case, "READ_RECORDING_AUDIO", resource(case, part)
                ),
            }
        )
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "parts": parts,
        "transcripts": transcripts,
        "command_id": str(uuid.uuid4()),
        "saved": saved,
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        yield _projection(case, guard, TranscriptBridge(case, guard))


@contextmanager
def save(
    *,
    case_ref,
    part_id,
    part_sha256,
    text,
    segments,
    change_kind,
    note,
    expected_version,
    command_id,
    expected_revision,
    expected_evidence_version,
    **common,
):
    cases._mutation_versions(expected_revision, expected_evidence_version)
    request_digest = recording._digest(
        [
            str(part_id),
            part_sha256,
            text,
            segments,
            change_kind,
            note,
            expected_version,
            expected_revision,
            expected_evidence_version,
        ]
    )
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        cases._versions(case, expected_revision, expected_evidence_version)
        bridge = TranscriptBridge(case, guard)
        part = _part(case, part_id, part_sha256)
        bridge.permit(guard.actor, "READ_TRANSCRIPT", recording._resource(part))
        bridge.permit(guard.actor, "EDIT_TRANSCRIPT", recording._resource(part))
        part, pins, _ = recording._source(bridge, guard.actor, part.pk)
        guard.finish()
        row, _actions, created = recording._append_transcript_locked(
            guard=bridge,
            actor=guard.actor,
            part=part,
            pins=pins,
            text=text,
            segments=segments,
            change_kind=change_kind,
            note=note,
            expected_version=expected_version,
            request_key=command_id,
            request_digest=request_digest,
        )
        if created:
            bridge.account_for_append(row)
        yield _projection(case, guard, bridge, saved=True)


@contextmanager
def decide(
    *,
    case_ref,
    transcript_id,
    transcript_digest,
    action,
    note,
    confirmed,
    expected_actions,
    command_id,
    expected_revision,
    expected_evidence_version,
    **common,
):
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if action not in recording.TRANSCRIPT_ACTIONS or confirmed is not True:
        raise cases.CaseConflict("recording_review_confirmation_required")
    request_digest = recording._digest(
        [
            str(transcript_id),
            transcript_digest,
            action,
            note,
            expected_actions,
            expected_revision,
            expected_evidence_version,
        ]
    )
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        if action == "APPROVE_MEANING" and guard.actor.role != "MUFTI":
            raise cases.CaseConflict("recording_meaning_mufti_required")
        cases._versions(case, expected_revision, expected_evidence_version)
        bridge = TranscriptBridge(case, guard)
        row, part, _, actions = recording._transcript(bridge, guard.actor, transcript_id)
        if row.digest != transcript_digest:
            raise cases.CaseConflict("operational_transcript_changed")
        bridge.permit(
            guard.actor,
            {
                "REVIEW": "REVIEW_TRANSCRIPT",
                "APPROVE_MEANING": "REVIEW_MEANING",
                "WITHDRAW": "WITHDRAW_TRANSCRIPT",
            }[action],
            recording._resource(part, row),
        )
        guard.finish()
        event, created = recording._append_transcript_action_locked(
            guard=bridge,
            actor=guard.actor,
            row=row,
            actions=actions,
            action=action,
            note=note,
            confirmed=confirmed,
            expected_actions=expected_actions,
            request_key=command_id,
            request_digest=request_digest,
        )
        if created:
            bridge.account_for_append(event)
        yield _projection(case, guard, bridge, saved=True)


@contextmanager
def audio_projection(*, case_ref, part_id, part_sha256, **common):
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        bridge = TranscriptBridge(case, guard)
        part = _part(case, part_id, part_sha256)
        guard.permit_resource(case, "READ_RECORDING_AUDIO", resource(case, part), required=True)
        bridge.permit(guard.actor, "READ_TRANSCRIPT", recording._resource(part))
        part, _, raw = recording._source(bridge, guard.actor, part.pk)
        yield {
            "raw": raw,
            "media_type": part.media_type,
            "filename": recording.safe_filename(part.pk, part.media_type),
        }
