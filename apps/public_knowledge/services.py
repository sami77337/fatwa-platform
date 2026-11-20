"""Native immutable curation; a human approval and an anonymous lease are distinct."""

import os
import re
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import _canonical as _json_canonical
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context, mutation_service

from .authority import PublicKnowledgeAuthority
from .models import PublicAction, PublicRevision, PublicSeries

KINDS = {"SCHOLAR", "TOPIC", "PRESENTATION", "LESSON"}
STAGES = {"DRAFT": "مسودة", "REVIEWED": "مراجعة", "APPROVED": "معتمدة", "WITHDRAWN": "مسحوبة"}


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("public_knowledge_disabled")


def languages():
    configured = getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_LANGUAGES", {"ar": "العربية"})
    if (
        type(configured) is not dict
        or "ar" not in configured
        or not 1 <= len(configured) <= 8
        or any(
            type(code) is not str
            or re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", code) is None
            or type(label) is not str
            or not 1 <= len(label) <= 40
            for code, label in configured.items()
        )
    ):
        raise cases.CaseConflict("public_languages_unconfigured")
    return dict(configured)


def _digest(value):
    return sha256(_json_canonical(value)).hexdigest()


def _text(value, maximum, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > maximum:
        raise cases.CaseConflict("public_knowledge_text_bound")
    return value


def _ids(value, limit=8):
    if type(value) is not list or len(value) > limit:
        raise cases.CaseConflict("public_knowledge_selection_invalid")
    result = [str(cases._uuid(item)) for item in value]
    if len(set(result)) != len(result):
        raise cases.CaseConflict("public_knowledge_selection_invalid")
    return result


def _epoch():
    authority = getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_AUTHORITY", None)
    if not isinstance(authority, PublicKnowledgeAuthority):
        raise cases.CaseConflict("public_knowledge_authority_required")
    try:
        value = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("public_knowledge_policy_snapshot_required") from exc
    if type(value) is not str or not value or len(value) > 2000:
        raise cases.CaseConflict("public_knowledge_policy_snapshot_required")
    return authority, value


def _same_epoch(expected):
    current = _epoch()
    return current[0] is expected[0] and current[1] == expected[1]


def _permit(actor, provider, case, action, kind, language=""):
    authority, _ = _epoch()
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            kind=kind,
            language=language,
        )
    except Exception as exc:
        raise cases.CaseConflict("public_knowledge_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("public_knowledge_action_denied")


def _identity_tuple(identity):
    return (
        identity.subject_id,
        identity.role,
        identity.active,
        identity.case_keys,
        identity.auth_epoch,
    )


def _source_configuration():
    """Configuration pins supplement the current source predicates, never grant use."""
    names = (
        "FATWA_LIBRARY_PREVIEW_ENABLED",
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
        "FATWA_CASE_CITATIONS_ENABLED",
        "FATWA_SOURCE_RIGHTS_ENFORCED",
        "FATWA_SOURCE_RIGHTS_ENABLED",
    )
    return tuple(
        (type(value), value) for value in (getattr(settings, name, None) for name in names)
    ) + (id(getattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", None)),)


def _canonical(case_ids):
    """Detect late nested source/rights changes after the last permission callback."""
    from apps.experimental_publication.models import PublicationAction

    result = [
        list(Case.objects.filter(pk__in=case_ids).order_by("pk").values()),
        list(PublicationEdition.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(
            PublicationAction.objects.filter(edition__case_id__in=case_ids).order_by("pk").values()
        ),
    ]
    if apps.is_installed("apps.source_rights"):
        from apps.source_rights.models import RightsAction, RightsRevision, SourceRegistration

        result.extend(
            [
                list(
                    SourceRegistration.objects.filter(case_id__in=case_ids).order_by("pk").values()
                ),
                list(RightsRevision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
                list(
                    RightsAction.objects.filter(revision__case_id__in=case_ids)
                    .order_by("pk")
                    .values()
                ),
            ]
        )
    return result


@mutation_context
@contextmanager
def staff_boundary(*, case_id, subject_id, provider, synthetic_fixtures_only=False, **pins):
    enabled()
    from . import scholarly

    namespace = provider.provider_id
    with (
        synthetic_queue_atomic(),
        scholarly.scope(subject_id=subject_id, provider=provider) as boundary,
        delivery._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ),
        _projection_expiry_guard(),
    ):
        if pins:
            cases._versions(case, pins["expected_revision"], pins["expected_evidence_version"])
        authority = _epoch()
        configured_languages = languages()
        source_case_ids = boundary.locked if boundary else [case.pk]
        source_state = _canonical(source_case_ids)
        source_configuration = _source_configuration()
        yield case, actor
        if boundary:
            boundary.permission_callbacks()
            boundary.identity_callbacks()
        fresh = cases._identity(provider, subject_id, case)
        if provider.provider_id != namespace or _identity_tuple(fresh) != _identity_tuple(actor):
            raise cases.CaseConflict("public_knowledge_identity_changed")
        if boundary:
            boundary.final_pins()
        if (
            _canonical(source_case_ids) != source_state
            or _source_configuration() != source_configuration
        ):
            raise cases.CaseConflict("public_knowledge_source_changed")
        if not _same_epoch(authority):
            raise cases.CaseConflict("public_knowledge_policy_changed")
        if languages() != configured_languages:
            raise cases.CaseConflict("public_knowledge_languages_changed")
        enabled()


def _source(case, publication_id):
    row = PublicationEdition.objects.filter(pk=cases._uuid(publication_id), case=case).first()
    if row is None:
        raise cases.CaseConflict("public_knowledge_source_unavailable")
    publication._approved(case, row)
    publication._verify(row)
    publication._require_publication_sources(case, row.citations)
    latest = (
        PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
        .order_by("-number")
        .first()
    )
    if (
        latest is None
        or latest.pk != row.pk
        or not preview._independent(row)
        or row.actions.filter(action="WITHDRAW").exists()
        or row.citations != publication._citation_snapshot(row.answer)
    ):
        raise cases.CaseConflict("public_knowledge_source_unavailable")
    return row


def _payload(kind, value, source, language):
    if type(value) is not dict:
        raise cases.CaseConflict("public_knowledge_payload_invalid")
    keys = {
        "SCHOLAR": {"name", "bio"},
        "TOPIC": {"title", "introduction", "parent_id"},
        "PRESENTATION": {
            "title",
            "question",
            "body",
            "description",
            "scholar_id",
            "topic_ids",
            "relation_ids",
        },
        "LESSON": {
            "title",
            "summary",
            "lesson_public_id",
            "lesson_version",
            "lesson_sha256",
            "scholar_ids",
            "topic_ids",
        },
    }
    if kind not in keys or set(value) != keys[kind]:
        raise cases.CaseConflict("public_knowledge_payload_invalid")
    result = dict(value)
    if kind == "SCHOLAR":
        _text(value["name"], 160)
        _text(value["bio"], 2000, optional=True)
    elif kind == "TOPIC":
        _text(value["title"], 160)
        _text(value["introduction"], 4000, optional=True)
        if value["parent_id"]:
            result["parent_id"] = str(cases._uuid(value["parent_id"]))
        elif value["parent_id"] != "":
            raise cases.CaseConflict("public_knowledge_payload_invalid")
    elif kind == "PRESENTATION":
        _text(value["title"], 160)
        _text(value["question"], 8000, optional=True)
        _text(value["description"], 320, optional=True)
        _text(value["body"], 16000, optional=language == "ar")
        if language == "ar" and (value["title"] != source.title or value["body"] != ""):
            raise cases.CaseConflict("arabic_original_is_immutable")
        if value["scholar_id"]:
            result["scholar_id"] = str(cases._uuid(value["scholar_id"]))
        elif value["scholar_id"] != "":
            raise cases.CaseConflict("public_knowledge_payload_invalid")
        result["topic_ids"] = _ids(value["topic_ids"])
        result["relation_ids"] = _ids(value["relation_ids"])
    else:
        _text(value["title"], 160)
        _text(value["summary"], 4000, optional=True)
        result["lesson_public_id"] = str(cases._uuid(value["lesson_public_id"]))
        if type(value["lesson_version"]) is not int or not 1 <= value["lesson_version"] <= 256:
            raise cases.CaseConflict("public_knowledge_lesson_invalid")
        if (
            type(value["lesson_sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", value["lesson_sha256"]) is None
        ):
            raise cases.CaseConflict("public_knowledge_lesson_invalid")
        result["scholar_ids"] = _ids(value["scholar_ids"])
        result["topic_ids"] = _ids(value["topic_ids"])
    return result


def _fingerprint(record):
    return _digest(
        [
            str(record.series_id),
            str(record.publication_id),
            record.number,
            record.case_revision,
            record.evidence_version,
            record.payload,
            record.provider_id,
            record.subject_id,
            record.auth_epoch,
            str(record.request_key),
        ]
    )


def _verify(record):
    if record.sha256 != _fingerprint(record):
        raise cases.CaseConflict("public_knowledge_record_changed")
    _payload(record.series.kind, record.payload, record.publication, record.series.language)
    if record.publication.case_id != record.series.case_id:
        raise cases.CaseConflict("public_knowledge_binding_changed")
    events = list(record.actions.order_by("sequence"))
    stage, reviewer, approved, leases, revoked = "DRAFT", None, None, {}, set()
    for number, event in enumerate(events, 1):
        if event.sequence != number or event.content_sha256 != record.sha256:
            raise cases.CaseConflict("public_knowledge_history_changed")
        actor = event.provider_id, event.subject_id
        creator = record.provider_id, record.subject_id
        if event.action == "REVIEW":
            if stage != "DRAFT" or actor == creator:
                raise cases.CaseConflict("public_knowledge_review_invalid")
            stage, reviewer = "REVIEWED", actor
        elif event.action == "APPROVE":
            if stage != "REVIEWED" or actor in {creator, reviewer}:
                raise cases.CaseConflict("public_knowledge_approval_invalid")
            stage, approved = "APPROVED", event
        elif event.action == "RELEASE":
            if (
                stage != "APPROVED"
                or event.expires_at is None
                or event.requested_minutes not in {5, 15, 30, 60}
            ):
                raise cases.CaseConflict("public_knowledge_release_invalid")
            leases[str(event.pk)] = event
        elif event.action == "REVOKE":
            if (
                stage != "APPROVED"
                or str(event.related_id) not in leases
                or event.related_id in revoked
            ):
                raise cases.CaseConflict("public_knowledge_revocation_invalid")
            revoked.add(event.related_id)
        elif event.action == "WITHDRAW":
            if stage == "WITHDRAWN":
                raise cases.CaseConflict("public_knowledge_withdrawal_invalid")
            stage = "WITHDRAWN"
        else:
            raise cases.CaseConflict("public_knowledge_history_changed")
    lease = next(reversed(leases.values()), None)
    if lease and (lease.pk in revoked or lease.expires_at <= timezone.now()):
        lease = None
    return events, stage, approved, lease


def _current_record(record_id, *, kind=None):
    row = (
        PublicRevision.objects.select_related("series", "publication__decision")
        .filter(pk=cases._uuid(record_id))
        .first()
    )
    if row is None or (kind and row.series.kind != kind):
        raise cases.CaseConflict("public_knowledge_record_unavailable")
    if row.series.revisions.order_by("-number").first().pk != row.pk:
        raise cases.CaseConflict("public_knowledge_record_superseded")
    _verify(row)
    return row


def _dependencies(record, *, actor, provider, case):
    """Only exact independently approved revisions may become curated associations."""
    value, kind = record.payload, record.series.kind
    selections = []
    if kind == "TOPIC" and value["parent_id"]:
        selections.append((value["parent_id"], "TOPIC"))
    if kind == "PRESENTATION" and value["scholar_id"]:
        selections.append((value["scholar_id"], "SCHOLAR"))
    if kind == "LESSON":
        selections.extend((item, "SCHOLAR") for item in value["scholar_ids"])
    selections.extend((item, "TOPIC") for item in value.get("topic_ids", []))
    for identifier, expected in selections:
        target = _current_record(identifier, kind=expected)
        # Native choices are case-scoped, never a way to fetch another private case.
        if target.series.case_id != case.pk or _verify(target)[1] != "APPROVED":
            raise cases.CaseConflict("public_knowledge_dependency_unavailable")
        _source(case, str(target.publication_id))
        _permit(actor, provider, case, "READ", expected, target.series.language)
        if expected == "SCHOLAR" and kind == "PRESENTATION":
            author = record.publication.answer
            if (target.series.author_provider, target.series.author_subject) != (
                author.provider_id,
                author.subject_id,
            ):
                raise cases.CaseConflict("public_scholar_attribution_mismatch")
    if kind == "TOPIC":
        seen, pointer = {record.series_id}, value["parent_id"]
        while pointer:
            parent = _current_record(pointer, kind="TOPIC")
            if parent.series_id in seen or len(seen) >= 5:
                raise cases.CaseConflict("public_topic_cycle_or_depth")
            seen.add(parent.series_id)
            pointer = parent.payload["parent_id"]
    if kind == "PRESENTATION" and value["relation_ids"]:
        from .scholarly import verify_relations

        verify_relations(record, actor=actor, provider=provider)
    if kind == "LESSON":
        from .scholarly import verify_lesson

        verify_lesson(record, actor=actor, provider=provider)


def _staff_row(record):
    events, stage, _, lease = _verify(record)
    return {
        "id": str(record.pk),
        "series_id": str(record.series_id),
        "kind": record.series.kind,
        "language": record.series.language,
        "number": record.number,
        "payload": record.payload,
        "sha256": record.sha256,
        "stage": stage,
        "stage_label": STAGES[stage],
        "action_count": len(events),
        "lease_id": str(lease.pk) if lease else "",
        "lease_until": lease.expires_at if lease else None,
        "history": [
            {"action": e.action, "note": e.note, "created_at": e.created_at, "actor": e.subject_id}
            for e in events
        ],
        "created_at": record.created_at,
        "kind_label": {
            "SCHOLAR": "صفحة عالم",
            "TOPIC": "موضوع بحثي",
            "PRESENTATION": "عرض الجواب أو ترجمته",
            "LESSON": "مادة درس",
        }[record.series.kind],
    }


@mutation_service
def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with staff_boundary(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    ) as (case, actor):
        current = (
            PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
            .order_by("-number")
            .first()
        )
        available = None
        if current:
            try:
                available = _source(case, str(current.pk))
            except cases.CaseConflict:
                pass
        rows = []
        for series in PublicSeries.objects.filter(case=case).order_by("created_at"):
            _permit(actor, provider, case, "READ", series.kind, series.language)
            record = series.revisions.order_by("-number").first()
            if record:
                row = _staff_row(record)
                row["publication_id"] = str(record.publication_id)
                row["versions"] = [
                    {"id": str(old.pk), "number": old.number, "created_at": old.created_at}
                    for old in series.revisions.order_by("-number")
                ]
                rows.append(row)
        from .scholarly import choices

        link_choices = choices(available, actor=actor, provider=provider) if available else {}
        return {
            **link_choices,
            "public_ref": case.public_ref,
            "case_id": str(case.pk),
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "records": rows,
            "languages": languages(),
            "publication": {
                "id": str(available.pk),
                "title": available.title,
                "body": available.body,
            }
            if available
            else None,
        }


@mutation_service
def read_revision(*, case_id, subject_id, provider, revision_id, synthetic_fixtures_only=False):
    with staff_boundary(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    ) as (case, actor):
        record = (
            PublicRevision.objects.select_related("series", "publication")
            .filter(pk=cases._uuid(revision_id), series__case=case)
            .first()
        )
        if record is None:
            raise cases.CaseConflict("public_knowledge_record_unavailable")
        _permit(actor, provider, case, "READ", record.series.kind, record.series.language)
        result = _staff_row(record)
        result["current"] = record.series.revisions.order_by("-number").first().pk == record.pk
        result["publication_id"] = str(record.publication_id)
        return result


@mutation_service
def save(
    *,
    case_id,
    subject_id,
    provider,
    publication_id,
    kind,
    language="",
    series_id="",
    expected_version,
    expected_revision,
    expected_evidence_version,
    payload,
    request_key,
    synthetic_fixtures_only=False,
):
    if kind not in KINDS or type(expected_version) is not int or not 0 <= expected_version < 128:
        raise cases.CaseConflict("public_knowledge_version_invalid")
    if (kind == "PRESENTATION" and language not in languages()) or (
        kind != "PRESENTATION" and language != ""
    ):
        raise cases.CaseConflict("public_knowledge_language_invalid")
    key = cases._uuid(request_key)
    with staff_boundary(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        _permit(actor, provider, case, "EDIT", kind, language)
        source = _source(case, publication_id)
        before = _canonical([case.pk])
        value = _payload(kind, payload, source, language)
        duplicate = PublicRevision.objects.filter(request_key=key).first()
        if duplicate:
            if (
                duplicate.series.case_id,
                duplicate.publication_id,
                duplicate.series.kind,
                duplicate.series.language,
                duplicate.payload,
                duplicate.provider_id,
                duplicate.subject_id,
                duplicate.auth_epoch,
                duplicate.number,
            ) != (
                case.pk,
                source.pk,
                kind,
                language,
                value,
                provider.provider_id,
                subject_id,
                actor.auth_epoch,
                expected_version + 1,
            ):
                raise cases.CaseConflict("public_knowledge_request_reused")
            _current_record(str(duplicate.pk))
            return _staff_row(duplicate)
        series = (
            PublicSeries.objects.select_for_update()
            .filter(pk=cases._uuid(series_id), case=case, kind=kind)
            .first()
            if series_id
            else None
        )
        if series_id and series is None:
            raise cases.CaseConflict("public_knowledge_series_unavailable")
        if series is None:
            values = dict(case=case, kind=kind, language=language)
            if kind == "SCHOLAR":
                values.update(
                    author_provider=source.answer.provider_id,
                    author_subject=source.answer.subject_id,
                )
                series = PublicSeries.objects.filter(
                    kind=kind,
                    author_provider=values["author_provider"],
                    author_subject=values["author_subject"],
                ).first()
            elif kind == "PRESENTATION":
                values["publication"] = source
                series = PublicSeries.objects.filter(
                    kind=kind, publication=source, language=language
                ).first()
            elif kind == "LESSON":
                values["external_id"] = cases._uuid(value["lesson_public_id"])
                series = PublicSeries.objects.filter(
                    kind=kind, external_id=values["external_id"]
                ).first()
            if series is None:
                if PublicSeries.objects.filter(case=case).count() >= 64 or expected_version:
                    raise cases.CaseConflict("public_knowledge_series_capacity_or_version")
                series = PublicSeries.objects.create(**values)
        if (
            series.case_id != case.pk
            or series.language != language
            or (kind == "PRESENTATION" and series.publication_id != source.pk)
        ):
            raise cases.CaseConflict("public_knowledge_series_binding_changed")
        if kind == "SCHOLAR" and (series.author_provider, series.author_subject) != (
            source.answer.provider_id,
            source.answer.subject_id,
        ):
            raise cases.CaseConflict("public_scholar_attribution_mismatch")
        if series.revisions.count() != expected_version:
            raise cases.CaseConflict("public_knowledge_version_conflict")
        record = PublicRevision(
            series=series,
            publication=source,
            number=expected_version + 1,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
            payload=value,
            request_key=key,
            provider_id=provider.provider_id,
            subject_id=subject_id,
            auth_epoch=actor.auth_epoch,
        )
        record.sha256 = _fingerprint(record)
        _dependencies(record, actor=actor, provider=provider, case=case)
        record.save(force_insert=True)
        _permit(actor, provider, case, "EDIT", kind, language)
        if _canonical([case.pk]) != before:
            raise cases.CaseConflict("public_knowledge_source_changed")
        _current_record(str(record.pk))
        return _staff_row(record)


@mutation_service
def act(
    *,
    case_id,
    subject_id,
    provider,
    revision_id,
    expected_actions,
    expected_revision,
    expected_evidence_version,
    action,
    request_key,
    note="",
    minutes=0,
    related_id="",
    confirmed=False,
    synthetic_fixtures_only=False,
):
    if (
        action not in {"REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW"}
        or confirmed is not True
    ):
        raise cases.CaseConflict("public_knowledge_confirmation_required")
    if type(expected_actions) is not int or not 0 <= expected_actions < 256:
        raise cases.CaseConflict("public_knowledge_action_version_invalid")
    _text(note, 2000, optional=action == "RELEASE")
    if action == "RELEASE" and (type(minutes) is not int or minutes not in {5, 15, 30, 60}):
        raise cases.CaseConflict("public_knowledge_release_duration_invalid")
    if action != "RELEASE" and minutes != 0:
        raise cases.CaseConflict("public_knowledge_release_duration_invalid")
    key = cases._uuid(request_key)
    with staff_boundary(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        record = _current_record(revision_id)
        if record.series.case_id != case.pk:
            raise cases.CaseConflict("public_knowledge_record_unavailable")
        kind, language = record.series.kind, record.series.language
        _permit(actor, provider, case, "WITHDRAW" if action == "REVOKE" else action, kind, language)
        events, stage, _, lease = _verify(record)
        related = cases._uuid(related_id) if related_id else None
        duplicate = PublicAction.objects.filter(request_key=key).first()
        if duplicate:
            if (
                duplicate.revision_id,
                duplicate.sequence,
                duplicate.action,
                duplicate.note,
                duplicate.related_id,
                duplicate.provider_id,
                duplicate.subject_id,
                duplicate.auth_epoch,
                duplicate.requested_minutes,
            ) != (
                record.pk,
                expected_actions + 1,
                action,
                note,
                related,
                provider.provider_id,
                subject_id,
                actor.auth_epoch,
                minutes,
            ):
                raise cases.CaseConflict("public_knowledge_request_reused")
            return _staff_row(record)
        if len(events) != expected_actions:
            raise cases.CaseConflict("public_knowledge_version_conflict")
        if action not in {"WITHDRAW", "REVOKE"}:
            _source(case, str(record.publication_id))
            _dependencies(record, actor=actor, provider=provider, case=case)
        before = _canonical([case.pk])
        owner = record.provider_id, record.subject_id
        current = provider.provider_id, subject_id
        if action == "REVIEW" and (stage != "DRAFT" or current == owner):
            raise cases.CaseConflict("independent_public_knowledge_review_required")
        if action == "APPROVE":
            reviewer = next((e for e in events if e.action == "REVIEW"), None)
            if (
                stage != "REVIEWED"
                or reviewer is None
                or current
                in {
                    owner,
                    (reviewer.provider_id, reviewer.subject_id),
                    (
                        record.publication.decision.provider_id,
                        record.publication.decision.subject_id,
                    ),
                }
            ):
                raise cases.CaseConflict("independent_public_knowledge_approval_required")
        if action in {"RELEASE", "REVOKE"} and stage != "APPROVED":
            raise cases.CaseConflict("public_knowledge_approval_required")
        if stage == "WITHDRAWN":
            raise cases.CaseConflict("public_knowledge_record_withdrawn")
        expires = None
        policy = None
        if action == "RELEASE":
            policy = preview.policy()
            with preview._current(policy, str(record.publication_id)):
                pass
            expires = min(timezone.now() + timedelta(minutes=minutes), policy.valid_until)
        if action == "REVOKE":
            if lease is None or lease.pk != related:
                raise cases.CaseConflict("public_knowledge_lease_unavailable")
        elif related is not None:
            raise cases.CaseConflict("public_knowledge_related_unexpected")
        PublicAction.objects.create(
            revision=record,
            sequence=len(events) + 1,
            action=action,
            request_key=key,
            note=note,
            content_sha256=record.sha256,
            expires_at=expires,
            requested_minutes=minutes,
            related_id=related,
            provider_id=provider.provider_id,
            subject_id=subject_id,
            auth_epoch=actor.auth_epoch,
        )
        _permit(actor, provider, case, "WITHDRAW" if action == "REVOKE" else action, kind, language)
        if _canonical([case.pk]) != before:
            raise cases.CaseConflict("public_knowledge_source_changed")
        if len(_verify(record)[0]) != expected_actions + 1:
            raise cases.CaseConflict("public_knowledge_history_changed")
        if policy is not None:
            preview._recheck(policy)
            if expires <= timezone.now():
                raise cases.CaseConflict("public_knowledge_release_expired")
        return _staff_row(record)
