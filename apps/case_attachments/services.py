"""Bounded attachment intake using the existing case locks and capability authority."""

import uuid

from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import CaseEvidence
from apps.private_media.storage import configured_storage
from apps.private_media.validation import MAX_BYTES as MAX_BYTES
from apps.private_media.validation import MediaValidationError, validate

from .models import CaseAttachment
from .storage_bindings import binding_locks, raw_for_owner, stored_fields

MAX_ATTACHMENTS = 32


def _enabled():
    if getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is not True:
        raise cases.CaseConflict("case_attachments_disabled")


def _validate(raw, filename, media_type):
    try:
        return validate(raw, filename, media_type)
    except MediaValidationError as exc:
        raise cases.CaseConflict(str(exc)) from exc


def upload(*, token, raw, filename, media_type, expected_revision, synthetic_fixtures_only=False):
    _enabled()
    media = _validate(raw, filename, media_type)
    storage = configured_storage()
    with (
        binding_locks(storage, [media.sha256]),
        cases._token_case(token, synthetic_fixtures_only) as case,
    ):
        cases._versions(case, expected_revision)
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        if CaseAttachment.objects.filter(case=case).count() >= MAX_ATTACHMENTS:
            raise cases.CaseConflict("attachment_capacity")
        attachment_id = uuid.uuid4()
        pointer = stored_fields(storage, media)
        digest = media.sha256
        text = f"مرفق السائل: {filename}\nSHA256: {digest}\nالحجم: {len(raw)} بايت"
        case.evidence_version += 1
        evidence = CaseEvidence.objects.create(
            case=case,
            version=case.evidence_version,
            kind="FOLLOWUP",
            text=text,
            text_sha256=cases._digest(text),
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        cases._event(case, "FOLLOWUP", case.requester_id, note="ATTACHMENT:" + str(attachment_id))
        row = CaseAttachment.objects.create(
            id=attachment_id,
            case=case,
            evidence=evidence,
            event=case.events.get(sequence=case.revision),
            **pointer,
            sha256=digest,
            size=len(raw),
            filename=filename,
            media_type=media.media_type,
            kind=media.kind,
            validation_metadata=media.metadata,
            subject_id=case.requester_id,
        )
        return _metadata(row)


def _metadata(row):
    return {
        "id": str(row.pk),
        "filename": row.filename,
        "sha256": row.sha256,
        "size": row.size,
        "media_type": row.media_type,
        "kind": row.kind,
        "validation_metadata": row.validation_metadata,
        "source": row.source,
        "created_at": row.created_at,
        "evidence_version": row.evidence.version,
    }


def _check(row):
    raw = raw_for_owner(row)
    if (
        len(raw) != row.size
        or row.evidence.case_id != row.case_id
        or row.event.case_id != row.case_id
        or row.evidence.kind != "FOLLOWUP"
        or row.event.action != "FOLLOWUP"
        or row.event.evidence_version != row.evidence.version
        or row.event.note != "ATTACHMENT:" + str(row.pk)
        or row.event.subject_id != row.subject_id
    ):
        raise cases.CaseConflict("attachment_integrity_failed")
    return raw


def _list(case):
    rows = (
        CaseAttachment.objects.filter(case=case)
        .select_related("evidence", "event")
        .order_by("evidence__version")
    )
    result = []
    for row in rows:
        _check(row)
        result.append(_metadata(row))
    return {"public_ref": case.public_ref, "revision": case.revision, "attachments": result}


def _read(case, attachment_id):
    row = (
        CaseAttachment.objects.filter(case=case, pk=cases._uuid(attachment_id))
        .select_related("evidence", "event")
        .first()
    )
    if row is None:
        raise cases.CaseConflict("attachment_unavailable")
    return {**_metadata(row), "raw": _check(row)}


def requester_list(*, token, synthetic_fixtures_only=False):
    _enabled()
    with cases._token_case(token, synthetic_fixtures_only) as case:
        return _list(case)


def requester_read(*, token, attachment_id, synthetic_fixtures_only=False):
    _enabled()
    with cases._token_case(token, synthetic_fixtures_only) as case:
        return _read(case, attachment_id)


def staff_list(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        return _list(case)


def staff_read(*, case_id, subject_id, provider, attachment_id, synthetic_fixtures_only=False):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        return _read(case, attachment_id)
