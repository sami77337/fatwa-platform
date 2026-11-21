"""Reuse exact authorized original readers; never use paths or hash dedup as scope."""

import json
from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.research_library import services as library
from apps.research_library.models import LibraryVersion
from apps.research_workspace.rights import ResearchRights, Resource, require
from apps.timed_citations.rights import TimedMediaRights

from .ledger import digest
from .policy import epoch

KINDS = frozenset({"ATTACHMENT", "ANSWER_PART", "LIBRARY_VERSION"})
MEDIA_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "audio/wav",
        "audio/mpeg",
        "audio/mp4",
        "video/webm",
        "video/mp4",
    }
)


@dataclass(frozen=True, slots=True)
class Source:
    kind: str
    identifier: str

    def validated(self):
        if (
            self.kind not in KINDS
            or type(self.identifier) is not str
            or str(cases._uuid(self.identifier)) != self.identifier
        ):
            raise cases.CaseConflict("derivative_source_invalid")
        return self


def _owner(guard, source):
    source.validated()
    model, ownership = {
        "ATTACHMENT": (CaseAttachment, "case_id"),
        "ANSWER_PART": (AnswerPart, "manifest__answer__case_id"),
        "LIBRARY_VERSION": (LibraryVersion, "item__case_id"),
    }[source.kind]
    row = model.objects.filter(pk=source.identifier, **{ownership: guard.case.pk}).first()
    if row is None:
        raise cases.CaseConflict("derivative_source_unavailable")
    return row


def _state(row, kind):
    # Immutable row metadata and current rights decisions, never original bytes.
    fields = [
        field.attname
        for field in row._meta.concrete_fields
        if field.get_internal_type() != "BinaryField"
    ]
    state = [list(type(row).objects.filter(pk=row.pk).values(*fields))]
    if kind == "LIBRARY_VERSION":
        state.append(list(row.decisions.order_by("sequence").values()))
    elif kind == "ANSWER_PART":
        state.append(list(type(row.manifest).objects.filter(pk=row.manifest_id).values()))
        state.append(
            list(type(row.manifest.answer).objects.filter(pk=row.manifest.answer_id).values())
        )
    else:
        state.append(list(type(row.evidence).objects.filter(pk=row.evidence_id).values()))
    return digest(json.loads(json.dumps(state, default=str)))


def read(guard, source, *, action, task):
    row = _owner(guard, source)
    initial = _state(row, source.kind)
    common = dict(
        case_id=guard.case.pk,
        subject_id=guard.actor.subject_id,
        provider=guard.provider,
        synthetic_fixtures_only=True,
    )
    descriptor = {"kind": source.kind, "id": str(row.pk)}
    if action == "DOWNLOAD":
        guard.permit("READ", task, descriptor)
    guard.permit(action, task, descriptor)
    exporting = action == "DOWNLOAD"
    if source.kind == "LIBRARY_VERSION":
        selected = library.policy_snapshot()
        result = library.file_content(version_id=row.pk, **common)
        if exporting:
            library.file_content(version_id=row.pk, usage="DOWNLOAD", **common)

        def rights():
            library.file_content(version_id=row.pk, **common)
            if exporting:
                library.file_content(version_id=row.pk, usage="DOWNLOAD", **common)

        def policy_pin():
            library.assert_policy_snapshot(selected)

        guard.deadline = min(guard.deadline, library._approval(row, "READ").valid_until)
    else:
        policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
        if not isinstance(policy, ResearchRights):
            raise cases.CaseConflict("derivative_source_rights_required")
        selected = epoch(policy)
        target = Resource(
            "ATTACHMENT" if source.kind == "ATTACHMENT" else "ANSWER_MEDIA", str(row.pk), row.sha256
        )

        def rights():
            require(guard.actor, guard.provider, guard.case, "READ_MEDIA", target)
            if isinstance(policy, TimedMediaRights):
                deadline = policy.grant_deadline(
                    provider_id=guard.provider.provider_id,
                    subject_id=guard.actor.subject_id,
                    auth_epoch=guard.actor.auth_epoch,
                    case_ref=guard.case.public_ref,
                    action="READ_MEDIA",
                    resource=target,
                )
                if deadline is None or timezone.is_naive(deadline) or deadline <= timezone.now():
                    raise cases.CaseConflict("derivative_source_expired")
                guard.deadline = min(guard.deadline, deadline)

        def policy_pin():
            if (
                getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None) is not policy
                or epoch(policy) != selected
            ):
                raise cases.CaseConflict("derivative_source_rights_changed")

        rights()
        result = (
            attachments.staff_read(attachment_id=row.pk, **common)
            if source.kind == "ATTACHMENT"
            else answers.staff_read(
                part_id=row.pk, **{key: value for key, value in common.items() if key != "case_id"}
            )
        )
    if exporting:
        from apps.data_privacy.integration import original as classified

        for kind, identifier in [("CASE", guard.case.pk), (source.kind, row.pk)]:
            classified(
                kind, identifier, provider=guard.provider, actor=guard.actor, action="EXPORT"
            )
        if source.kind == "ANSWER_PART":
            classified(
                "ANSWER",
                row.manifest.answer_id,
                provider=guard.provider,
                actor=guard.actor,
                action="EXPORT",
            )
        if source.kind != "LIBRARY_VERSION":
            from apps.selected_exports import policy as export_policy
            from apps.selected_exports.authority import ExportAuthority

            authority = getattr(settings, "FATWA_SELECTED_EXPORTS_AUTHORITY", None)
            if not isinstance(authority, ExportAuthority):
                raise cases.CaseConflict("derivative_source_export_required")
            selected_export = epoch(authority)

            def export_permission():
                export_policy.permit(
                    guard.case, guard.actor, guard.provider, "EXPORT_MEDIA", target
                )

            def export_pin():
                if (
                    getattr(settings, "FATWA_SELECTED_EXPORTS_AUTHORITY", None) is not authority
                    or epoch(authority) != selected_export
                ):
                    raise cases.CaseConflict("derivative_source_export_changed")

            export_permission()
            guard.callbacks.append(export_permission)
            guard.source_checks.append(export_pin)
    raw = result["raw"]
    if (
        result["media_type"] not in MEDIA_TYPES
        or type(raw) is not bytes
        or not 1 <= len(raw) <= 192000
    ):
        raise cases.CaseConflict("derivative_source_type_unavailable")
    if sha256(raw).hexdigest() != result["sha256"]:
        raise cases.CaseConflict("derivative_original_changed")
    if task == "THUMBNAIL" and not result["media_type"].startswith(("image/", "video/")):
        raise cases.CaseConflict("derivative_recipe_source_mismatch")
    if task == "AUDIO_PLAYBACK" and not result["media_type"].startswith(("audio/", "video/")):
        raise cases.CaseConflict("derivative_recipe_source_mismatch")
    pin = {
        **descriptor,
        "sha256": result["sha256"],
        "size": len(raw),
        "media_type": result["media_type"],
        "version_digest": initial,
    }

    def check():
        if _state(_owner(guard, source), source.kind) != initial:
            raise cases.CaseConflict("derivative_source_changed")
        policy_pin()

    guard.callbacks.append(rights)
    guard.source_checks.append(check)
    return pin, raw


def fields(source):
    return {
        {
            "ATTACHMENT": "attachment_id",
            "ANSWER_PART": "answer_part_id",
            "LIBRARY_VERSION": "library_version_id",
        }[source.kind]: source.identifier
    }
