"""Pre-read pins, current scoped actors and exact bytes through final rendering."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.casework import delivery
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context
from apps.research_workspace.rights import Resource, require
from apps.timed_citations.rights import TimedMediaRights

from .authority import AnswerMediaAuthority
from .models import PublicMediaAction, PublicMediaEdition, RecordingTranscript, TranscriptAction


class SourceChanged(cases.CaseConflict):
    """A canonical/publication change cannot be treated as an optional media fault."""


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("public_answer_media_disabled")


def _epoch(value, method, maximum=131072):
    try:
        result = getattr(value, method)()
    except Exception as exc:
        raise cases.CaseConflict("recording_projection_epoch_required") from exc
    if type(result) is not str or not 1 <= len(result) <= maximum:
        raise cases.CaseConflict("recording_projection_epoch_required")
    return result


def identity_pin(actor):
    return actor.subject_id, actor.role, actor.active, actor.case_keys, actor.auth_epoch


def core_state(case_id):
    from apps.public_knowledge.services import _canonical

    return _canonical([case_id])


def record_state(case_id):
    return [
        list(AnswerManifest.objects.filter(answer__case_id=case_id).order_by("pk").values()),
        list(AnswerPart.objects.filter(manifest__answer__case_id=case_id).order_by("pk").values()),
        list(RecordingTranscript.objects.filter(case_id=case_id).order_by("pk").values()),
        list(TranscriptAction.objects.filter(transcript__case_id=case_id).order_by("pk").values()),
        list(PublicMediaEdition.objects.filter(case_id=case_id).order_by("pk").values()),
        list(PublicMediaAction.objects.filter(edition__case_id=case_id).order_by("pk").values()),
    ]


CONFIG_NAMES = (
    "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED",
    "FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED",
    "FATWA_ANSWER_MEDIA_ENABLED",
    "FATWA_LIBRARY_PREVIEW_ENABLED",
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
    "FATWA_CASE_CITATIONS_ENABLED",
    "FATWA_SOURCE_RIGHTS_ENFORCED",
    "FATWA_SOURCE_RIGHTS_ENABLED",
)
OBJECT_NAMES = (
    "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY",
    "FATWA_CASEWORK_IDENTITY_PROVIDER",
    "FATWA_RESEARCH_WORKSPACE_RIGHTS",
    "FATWA_PRIVATE_MEDIA_STORAGE",
    "FATWA_LIBRARY_PREVIEW_POLICY",
    "FATWA_SOURCE_RIGHTS_AUTHORITY",
)


@dataclass
class ReadSnapshot:
    case_id: str
    provider: object
    authority: object
    media_policy: object
    provider_id: str
    identity_epoch: str
    authority_epoch: str
    media_epoch: str
    flags: tuple
    objects: tuple
    core: object
    records: object
    files: dict = field(default_factory=dict)
    deadlines: list = field(default_factory=list)


def snapshot(case_id, provider):
    """Capture before row/permission callbacks; callers must already own case scope.

    The object retains authority identities and receives only exact consumed-file
    pins while its projection is assembled. It never grants access by itself.
    """
    enabled()
    authority = getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY", None)
    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    if not isinstance(authority, AnswerMediaAuthority):
        raise cases.CaseConflict("recording_authority_required")
    if not isinstance(policy, TimedMediaRights):
        raise cases.CaseConflict("recording_media_rights_required")
    return ReadSnapshot(
        case_id=str(case_id),
        provider=provider,
        authority=authority,
        media_policy=policy,
        provider_id=getattr(provider, "provider_id", ""),
        identity_epoch=_epoch(provider, "projection_epoch"),
        authority_epoch=_epoch(authority, "projection_epoch"),
        media_epoch=_epoch(policy, "media_projection_epoch"),
        flags=tuple(
            (type(value), value) for value in (getattr(settings, key, None) for key in CONFIG_NAMES)
        ),
        objects=tuple(getattr(settings, key, None) for key in OBJECT_NAMES),
        core=core_state(case_id),
        records=record_state(case_id),
    )


def assert_snapshot(expected):
    """Final read-only check after ALL outer callbacks; no permission callbacks.

    projection_epoch and media_projection_epoch are required pure atomic reads.
    Actual original bytes are checked again; a stored digest alone is not proof.
    """
    enabled()
    # Storage adapters are external readers and may invoke callbacks. Complete
    # every byte read before the final side-effect-free policy/source checks.
    for part in expected.files.values():
        raw = media.raw_for_part(part)
        if len(raw) != part.size or sha256(raw).hexdigest() != part.sha256:
            raise cases.CaseConflict("recording_original_changed")
    assert_projection_state(expected)


def assert_projection_state(expected):
    """Pure final check for outer multi-case readers, after ALL their byte reads.

    No storage or permission adapter is called here. Policy/directory epoch
    getters are required side-effect-free atomic values by their explicit seam.
    """
    enabled()
    if core_state(expected.case_id) != expected.core:
        raise SourceChanged("recording_canonical_source_changed")
    if (
        any(
            getattr(settings, key, None) is not value
            for key, value in zip(OBJECT_NAMES, expected.objects)
        )
        or tuple(
            (type(value), value) for value in (getattr(settings, key, None) for key in CONFIG_NAMES)
        )
        != expected.flags
        or expected.provider.provider_id != expected.provider_id
        or _epoch(expected.provider, "projection_epoch") != expected.identity_epoch
        or _epoch(expected.authority, "projection_epoch") != expected.authority_epoch
        or _epoch(expected.media_policy, "media_projection_epoch") != expected.media_epoch
        or record_state(expected.case_id) != expected.records
    ):
        raise cases.CaseConflict("recording_projection_changed")
    if any(timezone.now() >= end for end in expected.deadlines):
        raise cases.CaseConflict("recording_permission_expired")


def _permit(authority, values):
    try:
        permitted = authority.permits(**{**values, "resource": dict(values["resource"])})
    except Exception as exc:
        raise cases.CaseConflict("recording_authority_unavailable") from exc
    if permitted is not True:
        raise cases.CaseConflict("recording_action_denied")


class Boundary:
    def __init__(self, case, provider):
        from apps.private_media.links import retain_projection

        self.case, self.provider = case, provider
        self.pin = snapshot(case.pk, provider)
        self.actors, self.permissions, self.media_permissions = {}, [], []
        retain_projection(lambda: assert_projection_state(self.pin))

    def actor(self, subject, epoch=None, provider_id=None):
        # RequestDirectory is deliberately bound to the signed-in subject.
        # Recorded authors/reviewers are re-resolved through the separately
        # pinned trusted directory, never through a fabricated browser identity.
        directory = (
            getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
            if epoch is not None or provider_id is not None
            else self.provider
        )
        if directory is None or directory.provider_id != self.provider.provider_id:
            raise cases.CaseConflict("recording_identity_changed")
        actor = cases._identity(directory, subject, self.case)
        if (epoch is not None and actor.auth_epoch != epoch) or (
            provider_id is not None and self.provider.provider_id != provider_id
        ):
            raise cases.CaseConflict("recording_identity_changed")
        self.actors[(id(directory), subject)] = (directory, identity_pin(actor))
        self.pin.deadlines.append(actor.valid_until)
        return actor

    def permit(self, actor, action, resource):
        values = dict(
            provider_id=self.provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=self.case.public_ref,
            action=action,
            resource=dict(resource),
        )
        self.permissions.append(values)
        _permit(self.pin.authority, values)

    def _media(self, actor, part):
        resource = Resource("ANSWER_MEDIA", str(part.pk), part.sha256)
        require(actor, self.provider, self.case, "READ_MEDIA", resource)
        try:
            end = self.pin.media_policy.grant_deadline(
                provider_id=self.provider.provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=self.case.public_ref,
                action="READ_MEDIA",
                resource=resource,
            )
            if timezone.is_naive(end) or end <= timezone.now():
                raise ValueError
        except Exception as exc:
            raise cases.CaseConflict("recording_media_expiry_required") from exc
        self.pin.deadlines.append(end)
        require(actor, self.provider, self.case, "READ_MEDIA", resource)

    def audio(self, actor, part):
        self.media_permissions.append((actor, part))
        self._media(actor, part)
        self.pin.files[str(part.pk)] = part
        return media.raw_for_part(part)

    def before_write(self):
        assert_snapshot(self.pin)

    def freeze_after_write(self):
        # Called immediately after one intentional append and before DTO callbacks.
        self.pin.records = record_state(self.case.pk)

    def callbacks(self):
        for values in self.permissions:
            _permit(self.pin.authority, values)
        for actor, part in self.media_permissions:
            self._media(actor, part)
        for (_, subject), (directory, expected) in self.actors.items():
            if identity_pin(cases._identity(directory, subject, self.case)) != expected:
                raise cases.CaseConflict("recording_identity_changed")

    def finish(self):
        self.callbacks()
        assert_snapshot(self.pin)


@mutation_context
@contextmanager
def staff_boundary(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    expected_revision=None,
    expected_evidence_version=None,
    **unused,
):
    enabled()
    with (
        synthetic_queue_atomic(),
        delivery._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ),
    ):
        if expected_revision is not None:
            cases._versions(case, expected_revision, expected_evidence_version)
        guard = Boundary(case, provider)
        guard.actor(subject_id)
        yield guard, actor
        guard.finish()
