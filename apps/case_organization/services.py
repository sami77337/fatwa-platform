"""Metadata never grants access, revises requester facts, or invalidates an answer."""

import os
from hashlib import sha256

from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue import services as queue
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .models import OrganizationRevision

QUESTION_TYPES = {
    "RULING": "الحكم",
    "VALIDITY": "الصحة والبطلان",
    "SUFFICIENCY": "الإجزاء والإعادة",
    "MAKEUP": "القضاء",
    "EXPIATION": "الكفارة أو الفدية",
    "COMPENSATION": "الضمان والتعويض",
    "RIGHTS": "الحقوق والالتزامات",
    "EFFECT": "وقوع الأثر الشرعي",
    "METHOD": "كيفية الفعل",
    "CALCULATION": "المقدار والحساب",
    "TIME": "الوقت",
    "CONDITIONS": "الشروط والموانع",
    "ELIGIBILITY": "الاستحقاق",
    "DISTRIBUTION": "التوزيع والقسمة",
    "DISPUTE": "الإثبات والنزاع",
    "CORRECTION": "تصحيح فعل سابق",
    "EDUCATION": "سؤال معرفي وتعليمي",
}


def enabled():
    return (
        os.environ.get("FATWA_PRODUCTION") == "0"
        and getattr(settings, "FATWA_CASE_ORGANIZATION_ENABLED", False) is True
    )


def _enabled():
    if not enabled():
        raise cases.CaseConflict("case_organization_disabled")


def _text(value, maximum, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > maximum:
        raise cases.CaseConflict("organization_text_too_long")


def _values(tags, question_types, note):
    if type(tags) is not list or len(tags) > 16 or type(question_types) is not list:
        raise cases.CaseConflict("organization_values_invalid")
    for tag in tags:
        _text(tag, 48)
        if tag != tag.strip() or "\n" in tag or "\r" in tag:
            raise cases.CaseConflict("organization_tag_invalid")
    if len(set(tags)) != len(tags) or len(question_types) > len(QUESTION_TYPES):
        raise cases.CaseConflict("organization_values_invalid")
    if any(type(key) is not str or key not in QUESTION_TYPES for key in question_types):
        raise cases.CaseConflict("organization_type_invalid")
    if len(set(question_types)) != len(question_types):
        raise cases.CaseConflict("organization_type_invalid")
    _text(note, 2000, optional=True)
    return {"tags": tags, "question_types": question_types, "note": note}


def _digest(value):
    return sha256(queue._canonical(value)).hexdigest()


def _rows(case):
    rows = list(OrganizationRevision.objects.filter(case=case).order_by("version")[:257])
    if len(rows) > 256:
        raise cases.CaseConflict("organization_history_invalid")
    for number, row in enumerate(rows, 1):
        value = _values(row.tags, row.question_types, row.note)
        if row.version != number or row.sha256 != _digest(value):
            raise cases.CaseConflict("organization_history_invalid")
    return rows


def _projection(case, rows):
    latest = rows[-1] if rows else None
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "metadata_version": latest.version if latest else 0,
        "tags": latest.tags if latest else [],
        "question_types": latest.question_types if latest else [],
        "history": [
            {
                "version": row.version,
                "tags": row.tags,
                "question_types": [QUESTION_TYPES[key] for key in row.question_types],
                "note": row.note,
                "subject_id": row.subject_id,
                "provider_id": row.provider_id,
                "created_at": row.created_at,
            }
            for row in reversed(rows)
        ],
    }


def _authorization(identity):
    # A directory may refresh a still-valid expiry without changing authority.
    # The resolver independently validates the current expiry on every call.
    return (
        identity.subject_id,
        identity.role,
        identity.active,
        identity.case_keys,
        identity.auth_epoch,
    )


def _recheck(case, actor, provider, provider_id):
    fresh = cases._identity(provider, actor.subject_id, case)
    if _authorization(fresh) != _authorization(actor) or provider.provider_id != provider_id:
        raise cases.CaseConflict("organization_identity_changed")


@mutation_service
def snapshot(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    provider_id = getattr(provider, "provider_id", None)
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        result = _projection(case, _rows(case))
        _recheck(case, actor, provider, provider_id)
        return result


@mutation_service
def save(
    *,
    case_id,
    subject_id,
    provider,
    tags,
    question_types,
    note,
    command_id,
    expected_metadata_version,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    _enabled()
    provider_id = getattr(provider, "provider_id", None)
    value = _values(tags, question_types, note)
    command = cases._uuid(command_id)
    if type(expected_metadata_version) is not int or not 0 <= expected_metadata_version < 256:
        raise cases.CaseConflict("organization_version_invalid")
    cases._mutation_versions(expected_revision, expected_evidence_version)
    command_sha = _digest(
        {
            **value,
            "metadata_version": expected_metadata_version,
            "revision": expected_revision,
            "evidence_version": expected_evidence_version,
        }
    )
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        rows = _rows(case)
        replay = next(
            (
                row
                for row in rows
                if row.command_id == command
                and row.subject_id == actor.subject_id
                and row.provider_id == provider.provider_id
            ),
            None,
        )
        if replay:
            if replay.command_sha256 != command_sha:
                raise cases.CaseConflict("organization_command_reused")
            _recheck(case, actor, provider, provider_id)
            return _projection(case, rows)
        cases._mutation_versions(expected_revision, expected_evidence_version)
        if (case.revision, case.evidence_version) != (expected_revision, expected_evidence_version):
            raise cases.CaseConflict("organization_case_changed")
        if len(rows) != expected_metadata_version:
            raise cases.CaseConflict("organization_version_changed")
        previous = rows[-1] if rows else None
        if (
            not note
            and tags == (previous.tags if previous else [])
            and question_types == (previous.question_types if previous else [])
        ):
            raise cases.CaseConflict("organization_no_change")
        row = OrganizationRevision.objects.create(
            case=case,
            version=len(rows) + 1,
            **value,
            sha256=_digest(value),
            command_id=command,
            command_sha256=command_sha,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        _recheck(case, actor, provider, provider_id)
        return _projection(case, [*rows, row])


@mutation_service
def search(
    *, subject_id, provider, query="", tag="", question_type="", synthetic_fixtures_only=False
):
    _enabled()
    try:
        actor = resolve_identity(provider, subject_id)
        provider_id = provider.provider_id
        with queue.synthetic_queue_atomic():
            # Match assignment batch lock order before list_cases acquires its
            # per-case locks in display order. Two workspaces must not deadlock
            # simply because creation order differs from UUID order.
            list(
                Case.objects.select_for_update()
                .filter(public_ref__in=actor.case_keys)
                .order_by("id")
                .values_list("id", flat=True)
            )
            result = _search(
                subject_id=subject_id,
                provider=provider,
                query=query,
                tag=tag,
                question_type=question_type,
                synthetic_fixtures_only=synthetic_fixtures_only,
            )
            if (
                _authorization(resolve_identity(provider, subject_id)) != _authorization(actor)
                or provider.provider_id != provider_id
            ):
                raise cases.CaseConflict("organization_identity_changed")
            return result
    except IdentityUnavailable as exc:
        raise cases.CaseConflict("case_access_denied") from exc


def _search(*, subject_id, provider, query, tag, question_type, synthetic_fixtures_only):
    _enabled()
    _text(query, 80, optional=True)
    _text(tag, 48, optional=True)
    _text(question_type, 32, optional=True)
    if question_type and question_type not in QUESTION_TYPES:
        raise cases.CaseConflict("organization_type_invalid")
    common = dict(
        subject_id=subject_id, provider=provider, synthetic_fixtures_only=synthetic_fixtures_only
    )
    # Authorization precedes inspecting metadata. No global tags/counts leak.
    rows = cases.list_cases(**common)
    results = []
    for row in rows:
        organized = snapshot(case_id=row["case_id"], **common)
        if tag and tag not in organized["tags"]:
            continue
        if question_type and question_type not in organized["question_types"]:
            continue
        texts = [
            row["public_ref"],
            row["original_question"],
            *(item["text"] for item in row["followups"]),
            *(item["text"] for item in row["answers"]),
        ]
        if query and not any(query.casefold() in text.casefold() for text in texts):
            continue
        results.append(
            {
                "public_ref": row["public_ref"],
                "tags": organized["tags"],
                "question_types": [QUESTION_TYPES[key] for key in organized["question_types"]],
            }
        )
    # Revalidate the entire previously authorized selection before returning it.
    fresh = cases.list_cases(**common)
    if [(r["public_ref"], r["revision"]) for r in rows] != [
        (r["public_ref"], r["revision"]) for r in fresh
    ]:
        raise cases.CaseConflict("organization_search_changed")
    return results
