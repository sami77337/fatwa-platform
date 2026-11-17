"""Bounded attachment intake using the existing case locks and capability authority."""

import re
import uuid
from hashlib import sha256

from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import CaseEvidence

from .models import CaseAttachment

MAX_BYTES = 65536
MAX_ATTACHMENTS = 32
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,95}\.txt", re.ASCII)


def _enabled():
    if getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is not True:
        raise cases.CaseConflict("case_attachments_disabled")


def _validate(raw, filename, media_type):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise cases.CaseConflict("attachment_size_invalid")
    if type(filename) is not str or _FILENAME.fullmatch(filename) is None:
        raise cases.CaseConflict("attachment_filename_invalid")
    if media_type != "text/plain":
        raise cases.CaseConflict("attachment_type_invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise cases.CaseConflict("attachment_encoding_invalid") from exc
    if not text.strip() or any((ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in text):
        raise cases.CaseConflict("attachment_text_invalid")
    return text


def upload(*, token, raw, filename, media_type, expected_revision, synthetic_fixtures_only=False):
    _enabled()
    _validate(raw, filename, media_type)
    with cases._token_case(token, synthetic_fixtures_only) as case:
        cases._versions(case, expected_revision)
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        if CaseAttachment.objects.filter(case=case).count() >= MAX_ATTACHMENTS:
            raise cases.CaseConflict("attachment_capacity")
        attachment_id = uuid.uuid4()
        digest = sha256(raw).hexdigest()
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
            original=raw,
            sha256=digest,
            size=len(raw),
            filename=filename,
            media_type=media_type,
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
        "source": row.source,
        "created_at": row.created_at,
        "evidence_version": row.evidence.version,
    }


def _check(row):
    raw = bytes(row.original)
    _validate(raw, row.filename, row.media_type)
    if (
        len(raw) != row.size
        or sha256(raw).hexdigest() != row.sha256
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
