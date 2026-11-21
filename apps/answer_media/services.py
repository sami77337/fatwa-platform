"""Human authored multipart revisions and separately approved private availability."""

import json
import os
import re
import uuid
from contextlib import contextmanager
from hashlib import sha256

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from apps.case_attachments.storage_bindings import (
    binding_locks,
    copied_pointer,
    raw_for_owner,
    stored_fields,
)
from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.delivery_queue.models import RequesterTrackingToken
from apps.platform_recovery.integration import mutation_context, mutation_service, require_admission
from apps.private_media.storage import configured_storage
from apps.private_media.validation import TYPES, MediaValidationError, validate

from . import youtube
from .editor_boundary import EditorBoundary, head
from .models import AnswerManifest, AnswerPart, PrivateAnswerRelease

MAX_PARTS = 8


def _metadata_valid(row):
    """Cheap read-time shape checks; full isolated parsing occurs at approval."""
    if row.kind == youtube.KIND:
        youtube.verify(row, raw_for_part(row))
        return True
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,94}\.[A-Za-z0-9]{2,4}", row.filename) is None:
        return False
    expected = TYPES.get("." + row.filename.rsplit(".", 1)[-1].lower())
    kind = (
        "AUDIO"
        if row.media_type.startswith("audio/")
        else "IMAGE"
        if row.media_type.startswith("image/")
        else "FILE"
    )
    data = row.metadata
    if (
        expected is None
        or expected[0] != row.media_type
        or row.kind != kind
        or type(data) is not dict
        or data.get("validated") is not True
    ):
        return False
    if row.media_type == "text/plain":
        return row.size <= 65536 and data == {"validated": True, "encoding": "UTF-8"}
    if row.media_type == "application/pdf":
        return (
            set(data) == {"validated", "pages", "active_content"}
            and type(data["pages"]) is int
            and 1 <= data["pages"] <= 10
            and data["active_content"] is False
        )
    if kind == "IMAGE":
        return (
            set(data) == {"validated", "width", "height", "format"}
            and type(data["width"]) is int
            and type(data["height"]) is int
            and data["width"] > 0
            and data["height"] > 0
            and data["width"] * data["height"] <= 4000000
            and data["format"]
            == {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[row.media_type]
        )
    return (
        set(data) == {"validated", "channels", "sample_rate", "duration_seconds"}
        and type(data["channels"]) is int
        and 1 <= data["channels"] <= 2
        and type(data["sample_rate"]) is int
        and 8000 <= data["sample_rate"] <= 96000
        and type(data["duration_seconds"]) in (int, float)
        and 0 < data["duration_seconds"] <= 120
    )


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("answer_media_disabled")


def _release_enabled():
    _enabled()
    if getattr(settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", False) is not True:
        raise cases.CaseConflict("private_answer_release_disabled")


def _digest(parts):
    values = [
        [
            str(p["id"]),
            p["ordinal"],
            p["kind"],
            p["sha256"],
            p["size"],
            p["media_type"],
            p["filename"],
            p["metadata"],
        ]
        for p in parts
    ]
    return sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fields(row):
    return {
        "id": str(row.pk),
        "ordinal": row.ordinal,
        "kind": row.kind,
        "sha256": row.sha256,
        "size": row.size,
        "media_type": row.media_type,
        "filename": row.filename,
        "metadata": row.metadata,
    }


def _verified(manifest):
    rows = list(manifest.parts.order_by("ordinal"))
    if len(rows) != manifest.part_count or not 2 <= len(rows) <= MAX_PARTS:
        raise cases.CaseConflict("answer_parts_inconsistent")
    for ordinal, row in enumerate(rows, 1):
        raw = raw_for_part(row)
        if (
            row.ordinal != ordinal
            or row.sha256 != sha256(raw).hexdigest()
            or len(raw) != row.size
            or row.source != "MUFTI_AUTHORED"
        ):
            raise cases.CaseConflict("answer_parts_inconsistent")
        if ordinal == 1:
            if (
                row.kind != "TEXT"
                or raw != manifest.answer.text.encode()
                or row.filename
                or row.metadata != {}
            ):
                raise cases.CaseConflict("answer_text_inconsistent")
        elif row.kind == "TEXT":
            raise cases.CaseConflict("answer_parts_inconsistent")
        elif not _metadata_valid(row):
            raise cases.CaseConflict("answer_media_metadata_inconsistent")
    if _digest([_fields(row) for row in rows]) != manifest.sha256:
        raise cases.CaseConflict("answer_manifest_inconsistent")
    return rows


@mutation_service
def save_multipart_answer(
    *,
    case_id,
    subject_id,
    provider,
    text,
    files,
    links=(),
    retained_part_ids=(),
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    _enabled()
    cases._text(text)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if any(type(value) not in (tuple, list) for value in (files, links, retained_part_ids)):
        raise cases.CaseConflict("answer_parts_invalid")
    if links and getattr(settings, "FATWA_ANSWER_LINKS_ENABLED", False) is not True:
        raise cases.CaseConflict("answer_links_disabled")
    linked = []
    for link in links:
        if type(link) is not dict or set(link) != {"url", "label"}:
            raise cases.CaseConflict("youtube_link_invalid")
        linked.append(youtube.validate(**link))
    if (
        not 1 <= len(files) + len(links) + len(retained_part_ids) < MAX_PARTS
        or any(type(value) is not str for value in retained_part_ids)
        or len(set(retained_part_ids)) != len(retained_part_ids)
    ):
        raise cases.CaseConflict("answer_parts_invalid")
    editor = (
        EditorBoundary(provider)
        if links
        or AnswerPart.objects.filter(
            pk__in=[cases._uuid(value) for value in retained_part_ids], kind=youtube.KIND
        ).exists()
        else None
    )
    checked = []
    try:
        for file in files:
            if type(file) is not dict or set(file) != {"raw", "filename", "media_type"}:
                raise cases.CaseConflict("answer_file_invalid")
            checked.append(validate(**file))
    except MediaValidationError as exc:
        raise cases.CaseConflict("answer_file_invalid") from exc
    storage = configured_storage()
    actor_provider_id = provider.provider_id
    with (
        binding_locks(storage, [media.sha256 for media in checked]),
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
    ):
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        retained = []
        if retained_part_ids:
            previous = AnswerManifest.objects.filter(
                answer__case=case, answer__revision=case.answer_revision
            ).first()
            if previous is None:
                raise cases.CaseConflict("retained_answer_parts_unavailable")
            available = {str(row.pk): row for row in _verified(previous) if row.ordinal > 1}
            for part_id in retained_part_ids:
                if part_id not in available:
                    raise cases.CaseConflict("retained_answer_parts_unavailable")
                row = available[part_id]
                retained.append({**_fields(row), **copied_pointer(row)})
        raw = text.encode()
        parts = [
            {
                "id": uuid.uuid4(),
                "ordinal": 1,
                "kind": "TEXT",
                "original": raw,
                "sha256": sha256(raw).hexdigest(),
                "size": len(raw),
                "media_type": "text/plain",
                "filename": "",
                "metadata": {},
            }
        ]
        for item in retained:
            parts.append({**item, "id": uuid.uuid4(), "ordinal": len(parts) + 1})
        for media in checked:
            kind = (
                "AUDIO"
                if media.media_type.startswith("audio/")
                else "IMAGE"
                if media.media_type.startswith("image/")
                else "FILE"
            )
            parts.append(
                {
                    "id": uuid.uuid4(),
                    "ordinal": len(parts) + 1,
                    "kind": kind,
                    **stored_fields(storage, media),
                    "sha256": media.sha256,
                    "size": media.size,
                    "media_type": media.media_type,
                    "filename": media.filename,
                    "metadata": media.metadata,
                }
            )
        for link in linked:
            parts.append(
                {
                    "id": uuid.uuid4(),
                    "ordinal": len(parts) + 1,
                    "kind": youtube.KIND,
                    "original": link.raw,
                    "sha256": link.sha256,
                    "size": link.size,
                    "media_type": link.media_type,
                    "filename": link.filename,
                    "metadata": link.metadata,
                }
            )
        current_actor = cases._identity(provider, subject_id, case)
        if (current_actor.subject_id, current_actor.auth_epoch, provider.provider_id) != (
            actor.subject_id,
            actor.auth_epoch,
            actor_provider_id,
        ):
            raise cases.CaseConflict("case_identity_changed")
        previous_answer = case.answers.order_by("-revision").first()
        case.answer_revision += 1
        answer = AnswerRevision.objects.create(
            case=case,
            revision=case.answer_revision,
            evidence_version=case.evidence_version,
            text=text,
            text_sha256=cases._digest(text),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        cases._event(case, "SAVE_ANSWER", actor.subject_id, answer=answer)
        manifest = AnswerManifest.objects.create(
            answer=answer, sha256=_digest(parts), part_count=len(parts)
        )
        for part in parts:
            AnswerPart.objects.create(manifest=manifest, **part)
        if (
            previous_answer
            and apps.is_installed("apps.case_citations")
            and previous_answer.citations.exists()
        ):
            from apps.case_citations.services import clone_citations_for_new_answer

            clone_citations_for_new_answer(previous_answer, answer)
        expected_head = (
            (
                case.revision,
                case.evidence_version,
                case.answer_revision,
                case.approved_answer_id,
                case.stage,
            ),
        )
        _verified(manifest)
        result = cases._staff(case)
        if editor:
            editor.check(actor)
            if head(case.pk) != expected_head:
                raise cases.CaseConflict("answer_editor_source_changed")
        return result


def _current(case, manifest):
    answer = manifest.answer
    if (
        case.stage != "ANSWERED"
        or case.approved_answer_id != answer.pk
        or case.evidence_version != answer.evidence_version
        or case.answer_revision != answer.revision
    ):
        raise cases.CaseConflict("current_multipart_approval_required")
    decision = answer.decision
    if (
        decision.action != "APPROVE"
        or decision.case_id != case.pk
        or decision.evidence_version != case.evidence_version
    ):
        raise cases.CaseConflict("current_multipart_approval_required")
    cases._answer_citations(answer)
    cases._answer_annotations(answer)
    _verified(manifest)
    return decision


@mutation_service
def release_private(
    *,
    case_id,
    subject_id,
    provider,
    expected_revision,
    expected_evidence_version,
    manifest_sha256,
    confirmed=False,
    synthetic_fixtures_only=False,
):
    _release_enabled()
    if confirmed is not True:
        raise cases.CaseConflict("explicit_private_release_required")
    cases._mutation_versions(expected_revision, expected_evidence_version)
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        manifest = AnswerManifest.objects.filter(answer_id=case.approved_answer_id).first()
        if manifest is None or manifest.sha256 != manifest_sha256:
            raise cases.CaseConflict("current_multipart_approval_required")
        decision = _current(case, manifest)
        release_provider_id = provider.provider_id
        validate_for_approval(manifest.answer)
        current_actor = cases._identity(provider, subject_id, case)
        if (current_actor.subject_id, current_actor.auth_epoch, provider.provider_id) != (
            actor.subject_id,
            actor.auth_epoch,
            release_provider_id,
        ):
            raise cases.CaseConflict("case_identity_changed")
        if (decision.subject_id, decision.provider_id, decision.auth_epoch) != (
            actor.subject_id,
            provider.provider_id,
            actor.auth_epoch,
        ):
            raise cases.CaseConflict("private_release_approver_changed")
        release, _ = PrivateAnswerRelease.objects.get_or_create(
            manifest=manifest,
            defaults={
                "decision": decision,
                "evidence_version": case.evidence_version,
                "manifest_sha256": manifest.sha256,
                "subject_id": actor.subject_id,
                "provider_id": provider.provider_id,
                "auth_epoch": actor.auth_epoch,
            },
        )
        return {
            "answer_revision": manifest.answer.revision,
            "available": True,
            "delivery_verified": False,
            "read_confirmed": False,
            "released_at": release.created_at,
        }


def _projection(case, manifest):
    from apps.data_privacy.integration import current as privacy

    privacy("ANSWER", manifest.answer_id)
    for identifier in manifest.parts.values_list("pk", flat=True):
        privacy("ANSWER_PART", identifier)
    parts = [_fields(row) for row in _verified(manifest)]
    current = bool(
        case.stage == "ANSWERED"
        and case.approved_answer_id == manifest.answer_id
        and manifest.answer.evidence_version == case.evidence_version
    )
    return {
        "answer_id": str(manifest.answer_id),
        "answer_revision": manifest.answer.revision,
        "evidence_version": manifest.answer.evidence_version,
        "sha256": manifest.sha256,
        "text": manifest.answer.text,
        "parts": parts,
        "approved": current,
        "released": current and PrivateAnswerRelease.objects.filter(manifest=manifest).exists(),
        "delivery_status": "UNSUPPORTED_MEDIA_REQUIRES_HUMAN_ACTION",
    }


def manifest_for_locked_answer(answer):
    """Internal core integration: caller already owns the authorized case lock.

    Deliberately independent of UI flags: existing manifests must remain verified
    on approval and transport preparation even if future editing is disabled.
    """
    manifest = AnswerManifest.objects.filter(answer=answer).first()
    if manifest is None:
        return None
    return {
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "text": answer.text,
        "sha256": manifest.sha256,
        "parts": [_fields(row) for row in _verified(manifest)],
        "requires_human_delivery": True,
    }


def validate_for_approval(answer):
    """Flag-independent, caller-locked full content check before human APPROVE.

    Re-run the bounded isolated parser so even a same-transaction internal write
    with fabricated MIME/metadata cannot be approved merely by matching hashes.
    File GETs use immutable hashes and cheap metadata checks instead of subprocesses.
    """
    manifest = AnswerManifest.objects.filter(answer=answer).first()
    if manifest is None:
        return None
    for row in _verified(manifest)[1:]:
        if row.kind == youtube.KIND:
            youtube.verify(row, raw_for_part(row))
            continue
        try:
            checked = validate(raw_for_part(row), row.filename, row.media_type)
        except MediaValidationError as exc:
            raise cases.CaseConflict("answer_media_content_invalid") from exc
        if (
            checked.sha256 != row.sha256
            or checked.size != row.size
            or checked.filename != row.filename
            or checked.media_type != row.media_type
            or checked.metadata != row.metadata
        ):
            raise cases.CaseConflict("answer_media_validation_changed")
    return manifest_for_locked_answer(answer)


def clone_parts_for_new_answer(previous, answer):
    """Internal cross-editor carry-forward in the caller's locked transaction.

    New part identities and manifest include the new canonical human text. No
    approval or private availability is inherited from the source revision.
    """
    require_admission()
    if previous is None:
        return None
    if previous.case_id != answer.case_id or previous.revision + 1 != answer.revision:
        raise cases.CaseConflict("answer_media_clone_binding_invalid")
    source = AnswerManifest.objects.filter(answer=previous).first()
    if source is None:
        return None
    rows = _verified(source)
    text = answer.text.encode()
    parts = [
        {
            "id": uuid.uuid4(),
            "ordinal": 1,
            "kind": "TEXT",
            "original": text,
            "sha256": sha256(text).hexdigest(),
            "size": len(text),
            "media_type": "text/plain",
            "filename": "",
            "metadata": {},
        }
    ]
    for row in rows[1:]:
        parts.append({**_fields(row), "id": uuid.uuid4(), **copied_pointer(row)})
    manifest = AnswerManifest.objects.create(
        answer=answer, sha256=_digest(parts), part_count=len(parts)
    )
    for part in parts:
        AnswerPart.objects.create(manifest=manifest, **part)
    _verified(manifest)
    return manifest_for_locked_answer(answer)


@mutation_service
def staff_snapshot(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    from apps.data_privacy.services import PrivacyDenied

    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        result = cases._staff(case)
        result["current_text"] = result["answers"][-1]["text"] if result["answers"] else ""
        result["packages"] = []
        for manifest in (
            AnswerManifest.objects.filter(answer__case=case)
            .select_related("answer")
            .order_by("-answer__revision")
        ):
            try:
                package = _projection(case, manifest)
            except PrivacyDenied:
                continue
            result["packages"].append(package)
        result["latest_package"] = next(
            (p for p in result["packages"] if p["answer_revision"] == case.answer_revision), None
        )
        return result


def _requester_manifest(case):
    from apps.data_privacy.integration import current as privacy

    manifest = AnswerManifest.objects.filter(answer_id=case.approved_answer_id).first()
    if manifest is None:
        raise cases.CaseConflict("private_multipart_unavailable")
    privacy("ANSWER", manifest.answer_id)
    decision = _current(case, manifest)
    release = PrivateAnswerRelease.objects.filter(manifest=manifest).first()
    if (
        release is None
        or release.decision_id != decision.pk
        or release.evidence_version != case.evidence_version
        or release.manifest_sha256 != manifest.sha256
    ):
        raise cases.CaseConflict("private_multipart_unavailable")
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if directory is None or getattr(directory, "provider_id", None) != release.provider_id:
        raise cases.CaseConflict("private_release_authority_unavailable")
    current = cases._identity(directory, release.subject_id, case)
    if current.auth_epoch != release.auth_epoch:
        raise cases.CaseConflict("private_release_authority_changed")
    return manifest


def _requester_pin(case, token):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    editor = (
        EditorBoundary(directory)
        if AnswerPart.objects.filter(
            manifest_id=case.approved_answer_id, kind=youtube.KIND
        ).exists()
        else None
    )
    grant = RequesterTrackingToken.objects.get(pk=cases._digest(token))
    return editor, head(case.pk), grant.case_id, grant.expires_at, grant.revoked_at


def _check_requester_pin(pin, case, token):
    editor, expected, tracking_id, expires, revoked = pin
    grant = RequesterTrackingToken.objects.get(pk=cases._digest(token))
    if (
        head(case.pk) != expected
        or grant.case_id != tracking_id
        or grant.expires_at != expires
        or grant.revoked_at != revoked
        or grant.revoked_at is not None
        or timezone.now() >= expires
    ):
        raise cases.CaseConflict("answer_requester_projection_changed")
    if editor:
        editor.check()


@mutation_service
def requester_snapshot(*, token, synthetic_fixtures_only=False):
    _release_enabled()
    with cases._token_case(token, synthetic_fixtures_only) as case:
        pin = _requester_pin(case, token)
        manifest = _requester_manifest(case)
        result = {
            "public_ref": case.public_ref,
            "package": _projection(case, manifest),
            "delivery_verified": False,
            "read_confirmed": False,
        }
        _check_requester_pin(pin, case, token)
        return result


@mutation_context
@contextmanager
def requester_page_projection(*, token, synthetic_fixtures_only=False):
    _release_enabled()
    with cases._token_case(token, synthetic_fixtures_only) as case:
        pin = _requester_pin(case, token)
        result = requester_snapshot(token=token, synthetic_fixtures_only=True)
        yield result
        if requester_snapshot(token=token, synthetic_fixtures_only=True) != result:
            raise cases.CaseConflict("answer_requester_projection_changed")
        _check_requester_pin(pin, case, token)


@mutation_service
def requester_read(*, token, part_id, synthetic_fixtures_only=False):
    from apps.data_privacy.integration import current as privacy

    _release_enabled()
    with cases._token_case(token, synthetic_fixtures_only) as case:
        pin = _requester_pin(case, token)
        manifest = _requester_manifest(case)
        privacy("ANSWER_PART", part_id)
        row = next(
            (p for p in _verified(manifest) if str(p.pk) == str(part_id) and p.ordinal > 1), None
        )
        if row is None:
            raise cases.CaseConflict("answer_part_unavailable")
        result = {**_fields(row), "raw": raw_for_part(row)}
        _check_requester_pin(pin, case, token)
        return result


@mutation_service
def staff_read(*, part_id, subject_id, provider, synthetic_fixtures_only=False):
    from apps.data_privacy.integration import current as privacy

    _enabled()
    row = (
        AnswerPart.objects.select_related("manifest__answer")
        .filter(pk=cases._uuid(part_id))
        .first()
    )
    if row is None:
        raise cases.CaseConflict("answer_part_unavailable")
    editor = EditorBoundary(provider) if row.kind == youtube.KIND else None
    with cases._staff_case(
        row.manifest.answer.case_id, subject_id, provider, synthetic_fixtures_only
    ) as (case, actor):
        privacy("ANSWER", row.manifest.answer_id)
        privacy("ANSWER_PART", row.pk)
        cases._answer_annotations(row.manifest.answer, actor=actor, provider=provider)
        cases._answer_citations(row.manifest.answer)
        _verified(row.manifest)
        if row.ordinal == 1:
            raise cases.CaseConflict("answer_part_unavailable")
        result = {**_fields(row), "raw": raw_for_part(row)}
        if editor:
            editor.check(actor)
        return result


def raw_for_part(row):
    """Exact original resolver for already-authorized internal callers; never a public URL."""
    return raw_for_owner(row)


def private_availability_for_locked_case(case):
    """Minimal current private availability, under the caller's requester case lock."""
    from apps.data_privacy.integration import current as privacy

    try:
        _release_enabled()
        manifest = _requester_manifest(case)
        for identifier in manifest.parts.values_list("pk", flat=True):
            privacy("ANSWER_PART", identifier)
    except cases.CaseConflict:
        return {"available": False, "answer_revision": None, "part_count": None}
    return {
        "available": True,
        "answer_revision": manifest.answer.revision,
        "part_count": manifest.part_count,
    }
