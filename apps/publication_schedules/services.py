"""One-shot due worker; it never changes the scheduled version or return channel."""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from hashlib import sha256

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication import services as publication
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.platform_recovery.integration import mutation_service
from apps.research_library.services import identity_snapshot

from .authority import ScheduleAuthority
from .models import PublicationSchedule, ScheduleOutcome

TARGET = "WEBSITE_PREVIEW"


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLICATION_SCHEDULES_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("publication_schedules_disabled")
    publication._enabled()


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _data(row):
    return {
        field.attname: (
            getattr(row, field.attname).isoformat(timespec="microseconds")
            if isinstance(getattr(row, field.attname), datetime)
            else getattr(row, field.attname)
        )
        for field in row._meta.fields
        if field.name not in {"canonical_payload", "digest", "created_at"}
    }


def _seal(row):
    row.canonical_payload = json.dumps(
        _data(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def verify(row):
    raw = json.dumps(
        _data(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    if raw != row.canonical_payload or sha256(raw.encode()).hexdigest() != row.digest:
        raise cases.CaseConflict("publication_schedule_history_changed")


def _epoch(authority, expected):
    if not isinstance(authority, expected):
        raise cases.CaseConflict("schedule_current_authority_required")
    reader = getattr(authority, "projection_epoch", None)
    try:
        result = reader() if callable(reader) else None
    except Exception:
        raise cases.CaseConflict("schedule_policy_unavailable") from None
    if type(result) is not str or not 1 <= len(result) <= 32768:
        raise cases.CaseConflict("schedule_policy_snapshot_required")
    return result


def snapshot(provider):
    enabled()
    from apps.casework_web.access import RequestDirectory

    configured = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if provider is not configured and not (
        isinstance(provider, RequestDirectory) and provider._provider is configured
    ):
        raise cases.CaseConflict("schedule_current_directory_required")
    schedule = getattr(settings, "FATWA_PUBLICATION_SCHEDULES_AUTHORITY", None)
    publishing = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None)
    return (
        id(schedule),
        _epoch(schedule, ScheduleAuthority),
        id(publishing),
        _epoch(publishing, PublicationAuthority),
        identity_snapshot(provider),
        identity_snapshot(configured),
    )


def _permit(actor, provider, case, action, edition, at):
    policy = getattr(settings, "FATWA_PUBLICATION_SCHEDULES_AUTHORITY", None)
    _epoch(policy, ScheduleAuthority)
    try:
        allowed = policy.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            edition_id=str(edition.pk),
            edition_sha256=edition.content_sha256,
            target=TARGET,
            scheduled_at=at.isoformat(),
        )
    except Exception:
        raise cases.CaseConflict("schedule_authority_unavailable") from None
    if allowed is not True:
        raise cases.CaseConflict("schedule_action_denied")


def _source(case, edition, *, published=False):
    publication._verify(edition)
    answer, decision = publication._approved(case, edition)
    publication._require_publication_sources(case, edition.citations)
    if edition.citations != publication._citation_snapshot(answer):
        raise cases.CaseConflict("schedule_citations_changed")
    actions = list(edition.actions.order_by("pk"))
    expected = {"REVIEW", "APPROVE"} if published else {"REVIEW"}
    if {
        row.action for row in actions
    } != expected or edition.number != PublicationEdition.objects.filter(case=case).count():
        raise cases.CaseConflict("schedule_review_or_version_changed")
    review = next(row for row in actions if row.action == "REVIEW")
    pin = [
        str(case.pk),
        case.revision,
        case.evidence_version,
        str(case.approved_answer_id),
        str(answer.pk),
        answer.revision,
        str(decision.pk),
        edition.content_sha256,
        str(review.pk),
        review.subject_id,
        review.provider_id,
        review.auth_epoch,
    ]
    return digest(pin), decision, review


def _independent(actor, provider, edition, decision, review):
    if (provider.provider_id, actor.subject_id) in {
        (edition.provider_id, edition.subject_id),
        (decision.provider_id, decision.subject_id),
        (review.provider_id, review.subject_id),
    }:
        raise cases.CaseConflict("independent_publication_scheduler_required")


def _dto(row):
    verify(row)
    outcome = ScheduleOutcome.objects.filter(schedule=row).first()
    if outcome:
        verify(outcome)
    state = outcome.action if outcome else "SCHEDULED"
    labels = {
        "SCHEDULED": "بانتظار الموعد",
        "PUBLISHED": "نُشرت النسخة المحددة",
        "CANCELLED": "أُلغي الموعد",
        "HOLD": "متوقف للمراجعة",
    }
    reasons = {
        "PUBLISHED": "اجتازت النسخة فحص المصدر والصلاحية الحالية عند الموعد.",
        "CANCELLED": "ألغى المستخدم هذا الموعد قبل النشر.",
        "HOLD": "تغير المصدر أو الصلاحية الحالية. يلزم مراجعة بشرية واختيار موعد جديد.",
    }
    return {
        "id": str(row.pk),
        "edition_id": str(row.edition_id),
        "edition_sha256": row.edition_sha256,
        "title": row.edition.title,
        "number": row.edition.number,
        "scheduled_at": row.scheduled_at,
        "target": row.target,
        "state": state,
        "state_label": labels[state],
        "reason_label": reasons.get(state, row.reason),
        "reason": outcome.reason if outcome else row.reason,
        "subject_id": row.subject_id,
        "created_at": row.created_at,
        "finished_at": outcome.created_at if outcome else None,
    }


@contextmanager
def boundary(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    enabled()
    before = snapshot(provider)
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        yield case, actor
        current = cases._identity(provider, subject_id, case)
        if current != actor or snapshot(provider) != before:
            raise cases.CaseConflict("schedule_current_context_changed")


@mutation_service
def prepare(
    *,
    edition_id,
    scheduled_at,
    target,
    expected_revision,
    expected_evidence_version,
    request_key,
    reason,
    confirmed,
    **common,
):
    if target != TARGET or confirmed is not True:
        raise cases.CaseConflict("schedule_explicit_target_required")
    if (
        type(scheduled_at) is not datetime
        or not timezone.is_aware(scheduled_at)
        or scheduled_at.utcoffset() != timedelta(0)
    ):
        raise cases.CaseConflict("schedule_utc_time_required")
    if (
        not timezone.now() + timedelta(seconds=2)
        <= scheduled_at
        <= timezone.now() + timedelta(days=30)
    ):
        raise cases.CaseConflict("schedule_future_time_required")
    cases._text(reason)
    if len(reason) > 500:
        raise cases.CaseConflict("schedule_reason_too_long")
    key = cases._uuid(request_key)
    with boundary(**common) as (case, actor):
        if case.revision != expected_revision or case.evidence_version != expected_evidence_version:
            raise cases.CaseConflict("schedule_case_changed")
        edition = PublicationEdition.objects.filter(pk=cases._uuid(edition_id), case=case).first()
        if edition is None:
            raise cases.CaseConflict("schedule_edition_unavailable")
        source, decision, review = _source(case, edition)
        _independent(actor, common["provider"], edition, decision, review)
        publication._authority(actor, common["provider"], case, "APPROVE")
        _permit(actor, common["provider"], case, "SCHEDULE", edition, scheduled_at)
        values = dict(
            edition=edition,
            request_key=key,
            edition_sha256=edition.content_sha256,
            source_sha256=source,
            target=target,
            scheduled_at=scheduled_at,
            subject_id=actor.subject_id,
            provider_id=common["provider"].provider_id,
            auth_epoch=actor.auth_epoch,
            reason=reason,
        )
        previous = PublicationSchedule.objects.filter(request_key=key).first()
        if previous:
            verify(previous)
            candidate = PublicationSchedule(id=previous.pk, **values)
            if _data(previous) != _data(candidate):
                raise cases.CaseConflict("schedule_idempotency_conflict")
            return _dto(previous)
        if PublicationSchedule.objects.filter(edition=edition, outcome__isnull=True).exists():
            raise cases.CaseConflict("edition_already_scheduled")
        if PublicationSchedule.objects.filter(edition__case=case).count() >= 64:
            raise cases.CaseConflict("schedule_capacity")
        row = _seal(PublicationSchedule(**values))
        if _source(case, edition)[0] != source:
            raise cases.CaseConflict("schedule_source_changed")
        return _dto(row)


def _finish(row, action, reason, *, actor=None, provider=None, publication_action=None):
    return _seal(
        ScheduleOutcome(
            schedule=row,
            action=action,
            reason=reason,
            actor_kind="STAFF" if actor else "WORKER",
            subject_id=actor.subject_id if actor else "due-worker",
            provider_id=provider.provider_id if actor else "synthetic-publication-scheduler",
            auth_epoch=actor.auth_epoch if actor else "current-trust-rechecked",
            publication_action=publication_action,
        )
    )


@mutation_service
def cancel(*, schedule_id, confirmed, **common):
    if confirmed is not True:
        raise cases.CaseConflict("schedule_confirmation_required")
    with boundary(**common) as (case, actor):
        row = (
            PublicationSchedule.objects.select_related("edition")
            .filter(pk=cases._uuid(schedule_id), edition__case=case)
            .first()
        )
        if row is None:
            raise cases.CaseConflict("schedule_unavailable")
        verify(row)
        _permit(actor, common["provider"], case, "CANCEL", row.edition, row.scheduled_at)
        outcome = ScheduleOutcome.objects.filter(schedule=row).first()
        if outcome:
            if outcome.action != "CANCELLED":
                raise cases.CaseConflict("schedule_already_terminal")
        else:
            _finish(
                row,
                "CANCELLED",
                "human_cancelled_exact_schedule",
                actor=actor,
                provider=common["provider"],
            )
        return _dto(row)


@mutation_service
def execute_due(*, schedule_id, provider, synthetic_fixtures_only=False):
    enabled()
    cases._guard(synthetic_fixtures_only)
    if provider is not getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None):
        raise cases.CaseConflict("schedule_worker_directory_required")
    with synthetic_queue_atomic():
        from apps.precise_citations.integration import prelock_cases

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        seed = (
            PublicationSchedule.objects.select_related("edition")
            .filter(pk=cases._uuid(schedule_id))
            .first()
        )
        if seed is None:
            raise cases.CaseConflict("schedule_unavailable")
        ids = prelock_cases([str(seed.edition.case_id)])
        list(Case.objects.filter(pk__in=ids).order_by("pk").select_for_update())
        row = (
            PublicationSchedule.objects.select_for_update()
            .select_related("edition")
            .get(pk=seed.pk)
        )
        verify(row)
        if (
            ScheduleOutcome.objects.filter(schedule=row).exists()
            or row.scheduled_at > timezone.now()
        ):
            return _dto(row)
        try:
            with transaction.atomic():
                with boundary(
                    case_id=row.edition.case_id,
                    subject_id=row.subject_id,
                    provider=provider,
                    synthetic_fixtures_only=True,
                ) as (case, actor):
                    before = snapshot(provider)
                    if (
                        provider.provider_id != row.provider_id
                        or actor.auth_epoch != row.auth_epoch
                    ):
                        raise cases.CaseConflict("schedule_identity_changed")
                    source, decision, review = _source(case, row.edition)
                    if (
                        source != row.source_sha256
                        or row.edition.content_sha256 != row.edition_sha256
                    ):
                        raise cases.CaseConflict("schedule_source_changed")
                    _independent(actor, provider, row.edition, decision, review)
                    _permit(actor, provider, case, "EXECUTE", row.edition, row.scheduled_at)
                    publication._authority(actor, provider, case, "APPROVE")
                    publication.act(
                        case_id=case.pk,
                        edition_id=row.edition_id,
                        subject_id=actor.subject_id,
                        provider=provider,
                        action="APPROVE",
                        synthetic_fixtures_only=True,
                    )
                    action = PublicationAction.objects.get(edition=row.edition, action="APPROVE")
                    if (
                        _source(case, row.edition, published=True)[0] != row.source_sha256
                        or snapshot(provider) != before
                    ):
                        raise cases.CaseConflict("schedule_final_source_changed")
                    _finish(
                        row,
                        "PUBLISHED",
                        "exact_scheduled_edition_approved",
                        actor=actor,
                        provider=provider,
                        publication_action=action,
                    )
        except cases.CaseConflict:
            # A failed current grant never becomes an approval. Keep the exact
            # schedule as a terminal HOLD; a human must prepare a new one.
            _finish(row, "HOLD", "source_or_current_authority_changed")
        return _dto(row)


@mutation_service
def run_due(*, limit=20):
    enabled()
    cases._guard(True)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise cases.CaseConflict("schedule_worker_limit_invalid")
    provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    ids = list(
        PublicationSchedule.objects.filter(outcome__isnull=True, scheduled_at__lte=timezone.now())
        .order_by("scheduled_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    counts = {"PUBLISHED": 0, "HOLD": 0, "CANCELLED": 0, "SCHEDULED": 0}
    for identifier in ids:
        result = execute_due(
            schedule_id=identifier, provider=provider, synthetic_fixtures_only=True
        )
        counts[result["state"]] += 1
    return counts


@mutation_service
def desk(**common):
    with boundary(**common) as (case, actor):
        rows = list(
            PublicationSchedule.objects.filter(edition__case=case)
            .select_related("edition")
            .order_by("-created_at")
        )
        editions = list(PublicationEdition.objects.filter(case=case).order_by("-number"))
        for edition in editions:
            _permit(
                actor,
                common["provider"],
                case,
                "VIEW",
                edition,
                timezone.now().astimezone(dt_timezone.utc),
            )
        return {
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "editions": [
                {"id": str(row.pk), "number": row.number, "title": row.title} for row in editions
            ],
            "rows": [_dto(row) for row in rows],
        }


@mutation_service
def run_for_staff(*, schedule_id, confirmed, **common):
    if confirmed is not True:
        raise cases.CaseConflict("schedule_confirmation_required")
    with boundary(**common) as (case, actor):
        row = (
            PublicationSchedule.objects.select_related("edition")
            .filter(pk=cases._uuid(schedule_id), edition__case=case)
            .first()
        )
        if row is None:
            raise cases.CaseConflict("schedule_unavailable")
        verify(row)
        _permit(actor, common["provider"], case, "RUN", row.edition, row.scheduled_at)
        return execute_due(
            schedule_id=row.pk,
            provider=getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            synthetic_fixtures_only=True,
        )
