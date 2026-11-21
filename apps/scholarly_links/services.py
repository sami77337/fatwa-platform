"""Manual lessons and typed links; existing cases, answers and recordings stay authoritative."""

import json
import os
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from hashlib import sha256

from django.conf import settings
from django.db import connection

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.mufti_review.identity import _ref, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .authority import ScholarlyAuthority
from .models import (
    KINDS,
    ZERO_HASH,
    CaseLessonLink,
    CaseRelation,
    Lesson,
    LessonCategory,
    LessonSeries,
    LessonVersion,
    LinkDecision,
    SeriesVersion,
)

KIND_LABELS = {
    "RELATED": "ذات صلة",
    "REFERRED_BY_SHEIKH": "أحال إليها الشيخ",
    "DUPLICATE_OF": "مكررة من",
    "SUPERSEDES": "تحل محل",
}
INVERSE_LABELS = {
    "RELATED": "ذات صلة",
    "REFERRED_BY_SHEIKH": "إحالة واردة إلى هذه القضية",
    "DUPLICATE_OF": "قضية أخرى مكررة من هذه القضية",
    "SUPERSEDES": "جواب قضية أخرى يحل محل هذه الفتوى",
}
STATE_LABELS = {
    "PROPOSED": "ربط مقترح ينتظر مراجعة بشرية",
    "APPROVE": "ربط اعتمده إنسان",
    "REJECT": "اقتراح مرفوض",
    "WITHDRAW": "ربط مسحوب",
}
MAX_SERIES = 32
MAX_LESSONS = 64
MAX_LINKS = 128


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_SCHOLARLY_LINKS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("scholarly_links_disabled")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, maximum, *, optional=False):
    if (
        type(value) is not str
        or len(value) > maximum
        or (not optional and not value.strip())
        or "\x00" in value
    ):
        raise cases.CaseConflict("scholarly_text_invalid")
    return value.strip()


def _integer(value, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise cases.CaseConflict("scholarly_version_invalid")
    return value


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise cases.CaseConflict("scholarly_identifier_invalid") from exc


def _payload(row):
    excluded = {"canonical_payload", "sha256", "transaction_id", "created_at"}
    result = {}
    for column in row._meta.concrete_fields:
        if column.attname in excluded:
            continue
        value = getattr(row, column.attname)
        result[column.attname] = str(value) if isinstance(value, uuid.UUID) else value
    return _json(result)


def _save(row):
    row.canonical_payload = _payload(row)
    row.sha256 = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    row.refresh_from_db()
    return row


def _verified(row):
    if (
        row.canonical_payload != _payload(row)
        or row.sha256 != sha256(row.canonical_payload.encode()).hexdigest()
        or row.transaction_id <= 0
    ):
        raise cases.CaseConflict("scholarly_history_invalid")
    return row


def _latest(model, field, owner):
    rows = list(model.objects.filter(**{field: owner}).order_by("number")[:129])
    previous = ZERO_HASH
    for number, row in enumerate(rows, 1):
        _verified(row)
        if row.number != number or row.previous_sha256 != previous or number > 128:
            raise cases.CaseConflict("scholarly_history_invalid")
        previous = row.sha256
    if not rows:
        raise cases.CaseConflict("scholarly_version_unavailable")
    return rows[-1]


def _audit(context, case, command_id):
    return dict(
        command_id=_uuid(command_id),
        subject_id=context.actor.subject_id,
        provider_id=context.provider_id,
        auth_epoch=context.actor.auth_epoch,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
    )


@dataclass
class ProjectionGuard:
    provider: object
    actor: object
    provider_id: str
    policy: ScholarlyAuthority
    epoch: str
    checks: list
    case_ids: tuple = ()
    fingerprint: str = ""
    part_pins: dict = field(default_factory=dict)

    def freeze(self, locked):
        self.case_ids = tuple(sorted(str(key) for key in locked))
        self.fingerprint = projection_fingerprint(self.case_ids)

    def permit(
        self, case, target, action, kind, resource_id="", resource_sha256="", *, required=True
    ):
        arguments = dict(
            provider_id=self.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=case.public_ref,
            target_case_ref=target.public_ref,
            action=action,
            kind=kind,
            resource_id=str(resource_id),
            resource_sha256=resource_sha256,
        )
        try:
            allowed = self.policy.permits(**arguments) is True
        except Exception as exc:
            raise cases.CaseConflict("scholarly_authority_unavailable") from exc
        if allowed:
            if arguments not in self.checks:
                self.checks.append(arguments)
        elif required:
            raise cases.CaseConflict("scholarly_action_denied")
        return allowed

    def check(self):
        if (
            getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None) is not self.policy
            or self.provider.provider_id != self.provider_id
        ):
            raise cases.CaseConflict("scholarly_authority_changed")
        try:
            for arguments in self.checks:
                if self.policy.permits(**arguments) is not True:
                    raise cases.CaseConflict("scholarly_authority_changed")
            fresh = resolve_identity(self.provider, self.actor.subject_id)
            if (
                (fresh.auth_epoch, fresh.role, fresh.case_keys)
                != (self.actor.auth_epoch, self.actor.role, self.actor.case_keys)
                or self.provider.provider_id != self.provider_id
                or getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None) is not self.policy
            ):
                raise cases.CaseConflict("scholarly_projection_changed")
            # No permission or identity callbacks follow these final source,
            # authority and row pins. A callback may have replaced the policy
            # object even when the old object's epoch remains unchanged.
            for part_id, expected in self.part_pins.items():
                part = (
                    AnswerPart.objects.select_related("manifest__answer").filter(pk=part_id).first()
                )
                if part is None or _source_snapshot(part) != expected:
                    raise cases.CaseConflict("lesson_source_changed")
            if self.policy.projection_epoch() != self.epoch:
                raise cases.CaseConflict("scholarly_projection_changed")
            if self.fingerprint and projection_fingerprint(self.case_ids) != self.fingerprint:
                raise cases.CaseConflict("scholarly_projection_changed")
        except cases.CaseConflict:
            raise
        except Exception as exc:
            raise cases.CaseConflict("scholarly_authority_unavailable") from exc
        _enabled()


def _graph_lock():
    # Call before retaining any canonical case locks, including in native
    # dispatchers which resolve their selected case before entering a service.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")


@contextmanager
def _scope(
    subject_id, provider, synthetic_fixtures_only, case_ids=None, *, graph=False, projection=False
):
    _enabled()
    cases._guard(synthetic_fixtures_only)
    actor = resolve_identity(provider, subject_id)
    provider_id = provider.provider_id
    policy = getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None)
    if not isinstance(policy, ScholarlyAuthority):
        raise cases.CaseConflict("scholarly_authority_required")
    try:
        epoch = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("scholarly_authority_unavailable") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 128:
        raise cases.CaseConflict("scholarly_policy_snapshot_required")
    guard = ProjectionGuard(provider, actor, provider_id, policy, epoch, [])
    requested = {_uuid(value) for value in case_ids} if case_ids is not None else None
    with synthetic_queue_atomic(), ExitStack() as stack:
        if graph or projection:
            # The SQL guard uses the same order, including for direct SQL writes.
            # This serializes directed graph changes across three or more cases.
            _graph_lock()
        identities = list(
            Case.objects.filter(public_ref__in=actor.case_keys)
            .order_by("id")
            .values_list("id", flat=True)
        )
        if requested is not None:
            if not requested.issubset(identities):
                raise cases.CaseConflict("scholarly_case_unavailable")
            identities = [value for value in identities if value in requested]
        if projection:
            # Lock the complete case set before its watermark, and before the
            # per-case identity callbacks or any row used to build the DTO.
            frozen = {
                case.pk: case
                for case in Case.objects.filter(pk__in=identities)
                .order_by("id")
                .select_for_update()
            }
            guard.freeze(frozen)
        locked = {}
        for case_id in identities:
            case, checked = stack.enter_context(
                cases._staff_case(case_id, subject_id, provider, True)
            )
            if (checked.auth_epoch, checked.case_keys) != (actor.auth_epoch, actor.case_keys):
                raise cases.CaseConflict("scholarly_projection_changed")
            locked[case.pk] = case
        # Mutation scopes intentionally stay unfrozen: their subsequent read
        # establishes a fresh baseline after the authorized command. Read scopes
        # must never reset their earlier baseline after a callback has run.
        yield locked, guard
        guard.check()


def _pins(case, expected_revision, expected_evidence_version):
    cases._mutation_versions(expected_revision, expected_evidence_version)
    cases._versions(case, expected_revision, expected_evidence_version)


def _teachers(value, case, guard):
    if type(value) is not list or not 1 <= len(value) <= 8:
        raise cases.CaseConflict("lesson_teachers_invalid")
    result, registered = [], []
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    for entry in value:
        if type(entry) is not dict or set(entry) not in (
            {"name"},
            {"name", "provider_id", "subject_id"},
        ):
            raise cases.CaseConflict("lesson_teachers_invalid")
        clean = {"name": _text(entry["name"], 160)}
        if "subject_id" in entry:
            if (
                entry["provider_id"] != guard.provider_id
                or getattr(directory, "provider_id", None) != guard.provider_id
            ):
                raise cases.CaseConflict("lesson_teacher_identity_unavailable")
            identity = resolve_identity(directory, entry["subject_id"], case_key=case.public_ref)
            clean.update(provider_id=guard.provider_id, subject_id=identity.subject_id)
            registered.append(identity)
        if clean in result:
            raise cases.CaseConflict("lesson_teachers_invalid")
        result.append(clean)
    return result, registered


def _check_teachers(registered, case, guard):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    for old in registered:
        fresh = resolve_identity(directory, old.subject_id, case_key=case.public_ref)
        if (fresh.auth_epoch, fresh.case_keys) != (
            old.auth_epoch,
            old.case_keys,
        ) or directory.provider_id != guard.provider_id:
            raise cases.CaseConflict("lesson_teacher_identity_changed")


def _replay(model, command_id, guard, expected):
    old = model.objects.filter(command_id=_uuid(command_id)).first()
    if old is None:
        return None
    _verified(old)
    if (
        old.provider_id != guard.provider_id
        or old.subject_id != guard.actor.subject_id
        or old.auth_epoch != guard.actor.auth_epoch
        or any(getattr(old, name) != value for name, value in expected.items())
    ):
        raise cases.CaseConflict("scholarly_command_conflict")
    return old


def _source_snapshot(part):
    media._enabled()
    rows = media._verified(part.manifest)
    if part.pk not in {row.pk for row in rows if row.ordinal > 1}:
        raise cases.CaseConflict("lesson_source_unavailable")
    answer = part.manifest.answer
    return {
        "kind": "ANSWER_MEDIA",
        "part_id": str(part.pk),
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "evidence_version": answer.evidence_version,
        "manifest_sha256": part.manifest.sha256,
        "sha256": part.sha256,
        "size": part.size,
        "media_type": part.media_type,
        "duration_ms": int(part.metadata["duration_seconds"] * 1000)
        if part.kind == "AUDIO"
        else None,
        "authored_by": answer.subject_id,
        "author_provider": answer.provider_id,
    }


def _source(part_id, case, guard):
    if part_id in (None, ""):
        return None, {}
    part = (
        AnswerPart.objects.select_related("manifest__answer")
        .filter(pk=_uuid(part_id), manifest__answer__case=case, ordinal__gt=1)
        .first()
    )
    if part is None:
        raise cases.CaseConflict("lesson_source_unavailable")
    guard.permit(case, case, "READ_MEDIA", "LESSON", part.pk, part.sha256)
    snapshot = _source_snapshot(part)
    guard.part_pins[str(part.pk)] = snapshot
    return part, snapshot


def _lesson(version, locked, guard, *, required=True):
    _verified(version)
    lesson = version.lesson
    case = locked.get(lesson.series.case_id)
    if case is None:
        if required:
            raise cases.CaseConflict("lesson_unavailable")
        return None
    if not guard.permit(
        case, case, "READ_LESSON", "LESSON", version.pk, version.sha256, required=required
    ):
        return None
    _verified(version.category)
    _verified(version.series_version)
    if version.category.case_id != case.pk or version.series_version.series_id != lesson.series_id:
        raise cases.CaseConflict("lesson_history_invalid")
    if version.source_part_id:
        current = _source_snapshot(version.source_part)
        if current != version.source_snapshot:
            raise cases.CaseConflict("lesson_source_changed")
        guard.part_pins[str(version.source_part_id)] = current
    elif version.source_snapshot:
        raise cases.CaseConflict("lesson_source_changed")
    return {
        "id": str(lesson.pk),
        "public_id": str(lesson.public_id),
        "version_id": str(version.pk),
        "version": version.number,
        "sha256": version.sha256,
        "title": version.title,
        "category_id": str(version.category_id),
        "category": version.category.label,
        "series_id": str(lesson.series_id),
        "series_public_id": str(lesson.series.public_id),
        "series_title": version.series_version.title,
        "series_version_id": str(version.series_version_id),
        "teachers": version.series_version.teachers,
        "source": version.source_snapshot,
        "source_available": bool(version.source_part_id),
        "can_read_media": bool(version.source_part_id)
        and guard.permit(
            case,
            case,
            "READ_MEDIA",
            "LESSON",
            version.source_part_id,
            version.source_part.sha256,
            required=False,
        ),
        "provenance": version.provenance,
        "owner_case_ref": case.public_ref,
        "owner_case_id": str(case.pk),
    }


def _status(link):
    previous, state = link.sha256, "PROPOSED"
    decisions = list(link.decisions.order_by("sequence"))
    for number, decision in enumerate(decisions, 1):
        _verified(decision)
        allowed = (
            {"APPROVE", "REJECT"}
            if state == "PROPOSED"
            else {"WITHDRAW"}
            if state == "APPROVE"
            else set()
        )
        if (
            decision.sequence != number
            or decision.previous_sha256 != previous
            or decision.action not in allowed
        ):
            raise cases.CaseConflict("scholarly_history_invalid")
        state, previous = decision.action, decision.sha256
    return state, decisions


def _answer(case, answer_id=None, *, approved=False):
    query = AnswerRevision.objects.filter(case=case)
    row = (
        query.filter(pk=_uuid(answer_id)).first()
        if answer_id is not None
        else query.order_by("-revision").first()
    )
    if row is None or row.text_sha256 != cases._digest(row.text):
        raise cases.CaseConflict("scholarly_answer_required")
    if approved:
        if not CaseDecision.objects.filter(answer=row, case=case, action="APPROVE").exists():
            raise cases.CaseConflict("scholarly_approved_target_required")
    elif row.revision != case.answer_revision or row.evidence_version != case.evidence_version:
        raise cases.CaseConflict("scholarly_answer_changed")
    return row


@mutation_service
def create_category(
    *,
    case_id,
    label,
    command_id,
    expected_revision,
    expected_evidence_version,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    label = _text(label, 120)
    with _scope(subject_id, provider, synthetic_fixtures_only, [case_id]) as (locked, guard):
        case = locked[_uuid(case_id)]
        _pins(case, expected_revision, expected_evidence_version)
        guard.permit(case, case, "MANAGE_LESSONS", "CATEGORY")
        old = _replay(LessonCategory, command_id, guard, {"case_id": case.pk, "label": label})
        if old is not None:
            return old
        if (
            LessonCategory.objects.filter(case=case).count() >= MAX_LESSONS
            or LessonCategory.objects.filter(case=case, label=label).exists()
        ):
            raise cases.CaseConflict("lesson_category_unavailable")
        return _save(LessonCategory(case=case, label=label, **_audit(guard, case, command_id)))


@mutation_service
def save_series(
    *,
    case_id,
    title,
    teachers,
    command_id,
    expected_revision,
    expected_evidence_version,
    subject_id,
    provider,
    series_id=None,
    expected_series_version=0,
    synthetic_fixtures_only=False,
):
    title = _text(title, 200)
    _integer(expected_series_version, zero=True)
    with _scope(subject_id, provider, synthetic_fixtures_only, [case_id]) as (locked, guard):
        case = locked[_uuid(case_id)]
        _pins(case, expected_revision, expected_evidence_version)
        guard.permit(case, case, "MANAGE_LESSONS", "SERIES", series_id or "")
        teachers, registered = _teachers(teachers, case, guard)
        old = _replay(SeriesVersion, command_id, guard, {"title": title, "teachers": teachers})
        if old is not None:
            if old.series.case_id != case.pk or (
                series_id is not None and old.series_id != _uuid(series_id)
            ):
                raise cases.CaseConflict("scholarly_command_conflict")
            _check_teachers(registered, case, guard)
            return old
        if series_id is None:
            if (
                expected_series_version != 0
                or LessonSeries.objects.filter(case=case).count() >= MAX_SERIES
            ):
                raise cases.CaseConflict("lesson_series_limit")
            series = LessonSeries.objects.create(case=case)
            number, previous, order = 1, ZERO_HASH, []
        else:
            series = LessonSeries.objects.filter(pk=_uuid(series_id), case=case).first()
            if series is None:
                raise cases.CaseConflict("lesson_series_unavailable")
            latest = _latest(SeriesVersion, "series", series)
            if latest.number != expected_series_version or latest.number >= 128:
                raise cases.CaseConflict("lesson_series_changed")
            number, previous, order = latest.number + 1, latest.sha256, latest.lesson_order
        result = _save(
            SeriesVersion(
                series=series,
                number=number,
                previous_sha256=previous,
                title=title,
                teachers=teachers,
                lesson_order=order,
                **_audit(guard, case, command_id),
            )
        )
        _check_teachers(registered, case, guard)
        return result


@mutation_service
def save_lesson(
    *,
    case_id,
    series_id,
    title,
    category_id,
    provenance,
    source_part_id,
    command_id,
    expected_revision,
    expected_evidence_version,
    expected_series_version,
    subject_id,
    provider,
    lesson_id=None,
    expected_lesson_version=0,
    synthetic_fixtures_only=False,
):
    title, provenance = _text(title, 200), _text(provenance, 1000)
    _integer(expected_lesson_version, zero=True)
    with _scope(subject_id, provider, synthetic_fixtures_only, [case_id]) as (locked, guard):
        case = locked[_uuid(case_id)]
        _pins(case, expected_revision, expected_evidence_version)
        series = LessonSeries.objects.filter(pk=_uuid(series_id), case=case).first()
        category = LessonCategory.objects.filter(pk=_uuid(category_id), case=case).first()
        if series is None or category is None:
            raise cases.CaseConflict("lesson_series_unavailable")
        latest_series = _latest(SeriesVersion, "series", series)
        _, registered = _teachers(latest_series.teachers, case, guard)
        guard.permit(case, case, "MANAGE_LESSONS", "SERIES", series.pk, latest_series.sha256)
        part, source = _source(source_part_id, case, guard)
        old = _replay(
            LessonVersion,
            command_id,
            guard,
            {
                "title": title,
                "category_id": category.pk,
                "provenance": provenance,
                "source_snapshot": source,
            },
        )
        if old is not None:
            if old.lesson.series_id != series.pk or (
                lesson_id is not None and old.lesson_id != _uuid(lesson_id)
            ):
                raise cases.CaseConflict("scholarly_command_conflict")
            return old
        if latest_series.number != _integer(expected_series_version):
            raise cases.CaseConflict("lesson_series_changed")
        if lesson_id is None:
            if (
                expected_lesson_version != 0
                or len(latest_series.lesson_order) >= MAX_LESSONS
                or latest_series.number >= 128
            ):
                raise cases.CaseConflict("lesson_limit")
            lesson = Lesson.objects.create(series=series)
            latest_series = _save(
                SeriesVersion(
                    series=series,
                    number=latest_series.number + 1,
                    previous_sha256=latest_series.sha256,
                    title=latest_series.title,
                    teachers=latest_series.teachers,
                    lesson_order=[*latest_series.lesson_order, str(lesson.pk)],
                    **_audit(guard, case, command_id),
                )
            )
            number, previous = 1, ZERO_HASH
        else:
            lesson = Lesson.objects.filter(pk=_uuid(lesson_id), series=series).first()
            if lesson is None:
                raise cases.CaseConflict("lesson_unavailable")
            latest = _latest(LessonVersion, "lesson", lesson)
            if latest.number != expected_lesson_version or latest.number >= 128:
                raise cases.CaseConflict("lesson_version_changed")
            number, previous = latest.number + 1, latest.sha256
        result = _save(
            LessonVersion(
                lesson=lesson,
                series_version=latest_series,
                number=number,
                previous_sha256=previous,
                title=title,
                category=category,
                source_part=part,
                source_snapshot=source,
                provenance=provenance,
                **_audit(guard, case, command_id),
            )
        )
        _check_teachers(registered, case, guard)
        return result


@mutation_service
def move_lesson(
    *,
    case_id,
    series_id,
    lesson_id,
    direction,
    command_id,
    expected_revision,
    expected_evidence_version,
    expected_series_version,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    if direction not in {"up", "down"}:
        raise cases.CaseConflict("lesson_direction_invalid")
    with _scope(subject_id, provider, synthetic_fixtures_only, [case_id]) as (locked, guard):
        case = locked[_uuid(case_id)]
        _pins(case, expected_revision, expected_evidence_version)
        series = LessonSeries.objects.filter(pk=_uuid(series_id), case=case).first()
        if series is None:
            raise cases.CaseConflict("lesson_series_unavailable")
        latest = _latest(SeriesVersion, "series", series)
        guard.permit(case, case, "MANAGE_LESSONS", "SERIES", series.pk, latest.sha256)
        # Reorder commands include their intended predecessor; a reused token
        # cannot become a different move after another edit.
        old = SeriesVersion.objects.filter(command_id=_uuid(command_id)).first()
        if old is not None:
            _verified(old)
            if (
                old.series_id != series.pk
                or old.number != expected_series_version + 1
                or old.subject_id != guard.actor.subject_id
                or old.provider_id != guard.provider_id
            ):
                raise cases.CaseConflict("scholarly_command_conflict")
            prior = SeriesVersion.objects.get(series=series, number=expected_series_version)
            wanted = _moved(prior.lesson_order, lesson_id, direction)
            if old.lesson_order != wanted:
                raise cases.CaseConflict("scholarly_command_conflict")
            return old
        if latest.number != _integer(expected_series_version) or latest.number >= 128:
            raise cases.CaseConflict("lesson_series_changed")
        return _save(
            SeriesVersion(
                series=series,
                number=latest.number + 1,
                previous_sha256=latest.sha256,
                title=latest.title,
                teachers=latest.teachers,
                lesson_order=_moved(latest.lesson_order, lesson_id, direction),
                **_audit(guard, case, command_id),
            )
        )


def _moved(order, lesson_id, direction):
    order = list(order)
    key = str(_uuid(lesson_id))
    if key not in order:
        raise cases.CaseConflict("lesson_unavailable")
    position = order.index(key)
    target = position - 1 if direction == "up" else position + 1
    if not 0 <= target < len(order):
        raise cases.CaseConflict("lesson_move_unavailable")
    order[position], order[target] = order[target], order[position]
    return order


@mutation_service
def propose_relation(
    *,
    case_id,
    target_case_id,
    target_answer_id,
    kind,
    reason,
    command_id,
    expected_revision,
    expected_evidence_version,
    expected_target_revision,
    expected_target_evidence_version,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    if kind not in KINDS or _uuid(case_id) == _uuid(target_case_id):
        raise cases.CaseConflict("scholarly_relation_invalid")
    reason = _text(reason, 1000)
    with _scope(
        subject_id, provider, synthetic_fixtures_only, [case_id, target_case_id], graph=True
    ) as (locked, guard):
        source, target = locked[_uuid(case_id)], locked[_uuid(target_case_id)]
        _pins(source, expected_revision, expected_evidence_version)
        _pins(target, expected_target_revision, expected_target_evidence_version)
        guard.permit(source, target, "PROPOSE", kind)
        answer, target_answer = _answer(source), _answer(target, target_answer_id, approved=True)
        values = dict(
            source_case=source,
            source_answer=answer,
            target_case=target,
            target_answer=target_answer,
            target_case_revision=target.revision,
            target_evidence_version=target.evidence_version,
            source_answer_sha256=answer.text_sha256,
            target_answer_sha256=target_answer.text_sha256,
            kind=kind,
            reason=reason,
        )
        old = _replay(
            CaseRelation,
            command_id,
            guard,
            {
                "source_case_id": source.pk,
                "source_answer_id": answer.pk,
                "target_case_id": target.pk,
                "target_answer_id": target_answer.pk,
                "kind": kind,
                "reason": reason,
            },
        )
        if old is not None:
            return old
        if CaseRelation.objects.filter(source_case=source).count() >= MAX_LINKS:
            raise cases.CaseConflict("scholarly_relation_limit")
        for prior in CaseRelation.objects.filter(
            source_answer=answer, target_answer=target_answer, kind=kind
        ):
            if _status(prior)[0] not in {"REJECT", "WITHDRAW"}:
                raise cases.CaseConflict("scholarly_relation_exists")
        return _save(CaseRelation(**values, **_audit(guard, source, command_id)))


def _span(version, start_ms, end_ms):
    if start_ms is None:
        if end_ms is not None:
            raise cases.CaseConflict("lesson_span_invalid")
        return
    _integer(start_ms, zero=True)
    if end_ms is not None:
        _integer(end_ms)
    duration = version.source_snapshot.get("duration_ms")
    if (
        type(duration) is not int
        or not 0 <= start_ms < duration
        or (end_ms is not None and not start_ms < end_ms <= duration)
    ):
        raise cases.CaseConflict("lesson_span_invalid")


@mutation_service
def propose_lesson_link(
    *,
    case_id,
    lesson_version_id,
    reason,
    command_id,
    expected_revision,
    expected_evidence_version,
    expected_target_revision,
    expected_target_evidence_version,
    subject_id,
    provider,
    start_ms=None,
    end_ms=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    cases._guard(synthetic_fixtures_only)
    version = (
        LessonVersion.objects.select_related(
            "lesson__series", "source_part__manifest__answer", "series_version", "category"
        )
        .filter(pk=_uuid(lesson_version_id))
        .first()
    )
    if version is None:
        raise cases.CaseConflict("lesson_unavailable")
    reason = _text(reason, 1000)
    with _scope(
        subject_id, provider, synthetic_fixtures_only, [case_id, version.lesson.series.case_id]
    ) as (locked, guard):
        source, target = locked[_uuid(case_id)], locked[version.lesson.series.case_id]
        _pins(source, expected_revision, expected_evidence_version)
        _pins(target, expected_target_revision, expected_target_evidence_version)
        _lesson(version, locked, guard)
        _span(version, start_ms, end_ms)
        guard.permit(source, target, "PROPOSE", "LESSON", version.pk, version.sha256)
        answer = _answer(source)
        row, _created = _append_lesson_link_locked(
            source=source,
            target=target,
            version=version,
            answer=answer,
            guard=guard,
            reason=reason,
            command_id=command_id,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        return row


def _append_lesson_link_locked(
    *, source, target, version, answer, guard, reason, command_id, start_ms, end_ms
):
    """Immutable persistence only; the caller owns exact scope/grants and source locks."""
    old = _replay(
        CaseLessonLink,
        command_id,
        guard,
        {
            "case_id": source.pk,
            "answer_id": answer.pk,
            "lesson_version_id": version.pk,
            "reason": reason,
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
    )
    if old is not None:
        return old, False
    if CaseLessonLink.objects.filter(case=source).count() >= MAX_LINKS:
        raise cases.CaseConflict("scholarly_relation_limit")
    for prior in CaseLessonLink.objects.filter(
        answer=answer, lesson_version=version, start_ms=start_ms, end_ms=end_ms
    ):
        if _status(prior)[0] not in {"REJECT", "WITHDRAW"}:
            raise cases.CaseConflict("scholarly_relation_exists")
    return _save(
        CaseLessonLink(
            case=source,
            answer=answer,
            answer_sha256=answer.text_sha256,
            lesson_version=version,
            target_case_revision=target.revision,
            target_evidence_version=target.evidence_version,
            start_ms=start_ms,
            end_ms=end_ms,
            reason=reason,
            **_audit(guard, source, command_id),
        )
    ), True


def _endpoints(link):
    if isinstance(link, CaseRelation):
        return link.source_case_id, link.target_case_id, link.kind
    return link.case_id, link.lesson_version.lesson.series.case_id, "LESSON"


def _verify_link(link):
    _verified(link)
    if isinstance(link, CaseRelation):
        pairs = [
            (link.source_answer, link.source_case_id, link.source_answer_sha256),
            (link.target_answer, link.target_case_id, link.target_answer_sha256),
        ]
    else:
        pairs = [(link.answer, link.case_id, link.answer_sha256)]
        _verified(link.lesson_version)
        _span(link.lesson_version, link.start_ms, link.end_ms)
    if any(
        answer.case_id != case_id
        or answer.text_sha256 != digest
        or cases._digest(answer.text) != digest
        for answer, case_id, digest in pairs
    ):
        raise cases.CaseConflict("scholarly_link_changed")
    return _status(link)


def _cycle(link):
    if not isinstance(link, CaseRelation) or link.kind not in {"DUPLICATE_OF", "SUPERSEDES"}:
        return False
    edges = {}
    for row in CaseRelation.objects.filter(kind=link.kind):
        if _status(row)[0] == "APPROVE":
            edges.setdefault(row.source_case_id, set()).add(row.target_case_id)
    pending, visited = [link.target_case_id], set()
    while pending:
        current = pending.pop()
        if current == link.source_case_id:
            return True
        if current not in visited:
            visited.add(current)
            pending.extend(edges.get(current, ()))
    return False


@mutation_service
def review_link(
    *,
    case_id,
    link_id,
    link_kind,
    action,
    note,
    command_id,
    expected_sequence,
    expected_revision,
    expected_evidence_version,
    expected_target_revision,
    expected_target_evidence_version,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    _enabled()
    cases._guard(synthetic_fixtures_only)
    if link_kind not in {"RELATION", "LESSON"} or action not in {"APPROVE", "REJECT", "WITHDRAW"}:
        raise cases.CaseConflict("scholarly_review_invalid")
    note = _text(note, 1000)
    model = CaseRelation if link_kind == "RELATION" else CaseLessonLink
    link = model.objects.filter(pk=_uuid(link_id)).first()
    if link is None:
        raise cases.CaseConflict("scholarly_link_unavailable")
    source_id, target_id, kind = _endpoints(link)
    if source_id != _uuid(case_id):
        raise cases.CaseConflict("scholarly_link_unavailable")
    with _scope(
        subject_id,
        provider,
        synthetic_fixtures_only,
        [source_id, target_id],
        graph=link_kind == "RELATION",
    ) as (locked, guard):
        source, target = locked[source_id], locked[target_id]
        _pins(source, expected_revision, expected_evidence_version)
        _pins(target, expected_target_revision, expected_target_evidence_version)
        _verify_link(link)
        guard.permit(source, target, action, kind, link.pk, link.sha256)
        if action == "APPROVE":
            if isinstance(link, CaseLessonLink):
                _lesson(link.lesson_version, locked, guard)
            else:
                _answer(target, link.target_answer_id, approved=True)
        row, _created = _append_link_decision_locked(
            source=source,
            target=target,
            link=link,
            action=action,
            note=note,
            command_id=command_id,
            expected_sequence=expected_sequence,
            guard=guard,
        )
        return row


def _append_link_decision_locked(
    *, source, target, link, action, note, command_id, expected_sequence, guard
):
    """Persist a checked transition; never grants review authority or changes an answer."""
    state, history = _verify_link(link)
    is_relation = isinstance(link, CaseRelation)
    old = _replay(
        LinkDecision,
        command_id,
        guard,
        {
            "relation_id": link.pk if is_relation else None,
            "lesson_link_id": None if is_relation else link.pk,
            "action": action,
            "note": note,
        },
    )
    if old is not None:
        return old, False
    if len(history) != _integer(expected_sequence, zero=True):
        raise cases.CaseConflict("scholarly_review_changed")
    allowed = (
        {"APPROVE", "REJECT"}
        if state == "PROPOSED"
        else {"WITHDRAW"}
        if state == "APPROVE"
        else set()
    )
    if action not in allowed or (action == "APPROVE" and _cycle(link)):
        raise cases.CaseConflict("scholarly_review_unavailable")
    return _save(
        LinkDecision(
            relation=link if is_relation else None,
            lesson_link=None if is_relation else link,
            sequence=len(history) + 1,
            previous_sha256=history[-1].sha256 if history else link.sha256,
            target_case_revision=target.revision,
            target_evidence_version=target.evidence_version,
            action=action,
            note=note,
            **_audit(guard, source, command_id),
        )
    ), True


def _link_projection(link, current, locked, guard):
    source_id, target_id, kind = _endpoints(link)
    source, target = locked.get(source_id), locked.get(target_id)
    if source is None or target is None:
        return None
    state, history = _verify_link(link)
    # READ is explicit for links too; no sensitive decision grants are inferred.
    if not guard.permit(source, target, "READ_LINK", kind, link.pk, link.sha256, required=False):
        return None
    is_relation = isinstance(link, CaseRelation)
    lesson = None if is_relation else _lesson(link.lesson_version, locked, guard, required=False)
    if not is_relation and lesson is None:
        return None
    outgoing = current.pk == source_id
    return {
        "id": str(link.pk),
        "sha256": link.sha256,
        "link_kind": "RELATION" if is_relation else "LESSON",
        "kind": kind,
        "label": KIND_LABELS[kind]
        if is_relation and outgoing
        else INVERSE_LABELS[kind]
        if is_relation
        else "تناول المسألة في درس",
        "outgoing": outgoing,
        "source_case_ref": source.public_ref,
        "target_case_ref": target.public_ref,
        "source_answer_id": str(link.source_answer_id if is_relation else link.answer_id),
        "source_answer_revision": link.source_answer.revision
        if is_relation
        else link.answer.revision,
        "target_answer_id": str(link.target_answer_id) if is_relation else "",
        "target_answer_revision": link.target_answer.revision if is_relation else None,
        "state": state,
        "state_label": STATE_LABELS[state],
        "sequence": len(history),
        "reason": link.reason,
        "created_at": link.created_at,
        "created_by": link.subject_id,
        "lesson": lesson,
        "start_ms": None if is_relation else link.start_ms,
        "end_ms": None if is_relation else link.end_ms,
        "target_revision": target.revision,
        "target_evidence_version": target.evidence_version,
        "can_approve": outgoing
        and state == "PROPOSED"
        and guard.permit(source, target, "APPROVE", kind, link.pk, link.sha256, required=False),
        "can_reject": outgoing
        and state == "PROPOSED"
        and guard.permit(source, target, "REJECT", kind, link.pk, link.sha256, required=False),
        "can_withdraw": outgoing
        and state == "APPROVE"
        and guard.permit(source, target, "WITHDRAW", kind, link.pk, link.sha256, required=False),
        "history": [
            {
                "action": row.action,
                "label": STATE_LABELS[row.action],
                "note": row.note,
                "actor": row.subject_id,
                "created_at": row.created_at,
            }
            for row in history
        ],
    }


def _catalog(locked, guard):
    series_rows, lessons = [], []
    for series in LessonSeries.objects.filter(case_id__in=locked).order_by("created_at", "id"):
        current = _latest(SeriesVersion, "series", series)
        owner = locked[series.case_id]
        if not guard.permit(
            owner, owner, "READ_LESSON", "SERIES", current.pk, current.sha256, required=False
        ):
            continue
        rows = []
        if set(current.lesson_order) != {
            str(value) for value in series.lessons.values_list("id", flat=True)
        }:
            raise cases.CaseConflict("lesson_order_invalid")
        for position, lesson_id in enumerate(current.lesson_order, 1):
            version = _latest(LessonVersion, "lesson_id", _uuid(lesson_id))
            row = _lesson(version, locked, guard, required=False)
            if row is None:
                continue
            row.update(
                position=position,
                can_move_up=position > 1,
                can_move_down=position < len(current.lesson_order),
                owner_revision=owner.revision,
                owner_evidence_version=owner.evidence_version,
            )
            rows.append(row)
            lessons.append(row)
        series_rows.append(
            {
                "id": str(series.pk),
                "public_id": str(series.public_id),
                "version_id": str(current.pk),
                "version": current.number,
                "sha256": current.sha256,
                "title": current.title,
                "teachers": current.teachers,
                "lessons": rows,
                "owner_case_ref": owner.public_ref,
                "owner_case_id": str(owner.pk),
                "can_manage": guard.permit(
                    owner,
                    owner,
                    "MANAGE_LESSONS",
                    "SERIES",
                    series.pk,
                    current.sha256,
                    required=False,
                ),
            }
        )
    return series_rows, lessons


@mutation_service
def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with _scope(subject_id, provider, synthetic_fixtures_only, projection=True) as (locked, guard):
        current = locked.get(_uuid(case_id))
        if current is None:
            raise cases.CaseConflict("scholarly_case_unavailable")
        catalog, lessons = _catalog(locked, guard)
        relations = []
        from django.db.models import Q

        for row in CaseRelation.objects.filter(
            Q(source_case=current) | Q(target_case=current)
        ).order_by("created_at", "id"):
            projection = _link_projection(row, current, locked, guard)
            if projection is not None:
                relations.append(projection)
        links = []
        for row in CaseLessonLink.objects.filter(case=current).order_by("created_at", "id"):
            projection = _link_projection(row, current, locked, guard)
            if projection is not None:
                links.append(projection)
        targets = []
        for target in locked.values():
            if target.pk == current.pk:
                continue
            for decision in (
                target.decisions.filter(action="APPROVE")
                .select_related("answer")
                .order_by("-answer__revision")[:16]
            ):
                targets.append(
                    {
                        "case_id": str(target.pk),
                        "case_ref": target.public_ref,
                        "answer_id": str(decision.answer_id),
                        "answer_revision": decision.answer.revision,
                        "revision": target.revision,
                        "evidence_version": target.evidence_version,
                    }
                )
        parts = []
        for part in (
            AnswerPart.objects.filter(manifest__answer__case=current, ordinal__gt=1)
            .select_related("manifest__answer")
            .order_by("manifest__answer__revision", "ordinal")[:128]
        ):
            if guard.permit(
                current, current, "READ_MEDIA", "LESSON", part.pk, part.sha256, required=False
            ):
                guard.part_pins[str(part.pk)] = _source_snapshot(part)
                parts.append(
                    {
                        "id": str(part.pk),
                        "answer_revision": part.manifest.answer.revision,
                        "ordinal": part.ordinal,
                        "kind": part.kind,
                        "filename": part.filename,
                    }
                )
        categories = list(LessonCategory.objects.filter(case=current).order_by("label", "id"))
        for category in categories:
            _verified(category)
        latest_answer = current.answers.order_by("-revision").first()
        return {
            "case_ref": current.public_ref,
            "case_id": str(current.pk),
            "revision": current.revision,
            "evidence_version": current.evidence_version,
            "has_answer": latest_answer is not None
            and latest_answer.evidence_version == current.evidence_version,
            "series": catalog,
            "own_series": [row for row in catalog if row["owner_case_id"] == str(current.pk)],
            "lessons": lessons,
            "categories": categories,
            "parts": parts,
            "relations": relations,
            "lesson_links": links,
            "targets": targets,
            "can_manage": guard.permit(
                current, current, "MANAGE_LESSONS", "SERIES", required=False
            ),
            "_guard": guard,
        }


@mutation_service
def read_lesson(*, case_id, lesson_version_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    cases._guard(synthetic_fixtures_only)
    version = (
        LessonVersion.objects.select_related(
            "lesson__series", "source_part__manifest__answer", "category", "series_version"
        )
        .filter(pk=_uuid(lesson_version_id))
        .first()
    )
    if version is None:
        raise cases.CaseConflict("lesson_unavailable")
    with _scope(
        subject_id,
        provider,
        synthetic_fixtures_only,
        [case_id, version.lesson.series.case_id],
        projection=True,
    ) as (locked, guard):
        result = _lesson(version, locked, guard)
        result["history"] = [
            {
                "id": str(row.pk),
                "version": row.number,
                "title": row.title,
                "created_at": row.created_at,
                "actor": row.subject_id,
            }
            for row in version.lesson.versions.order_by("number")
            if _lesson(row, locked, guard, required=False) is not None
        ]
        result["_guard"] = guard
        return result


@mutation_service
def open_lesson_media(
    *, case_id, lesson_version_id, subject_id, provider, synthetic_fixtures_only=False
):
    _enabled()
    cases._guard(synthetic_fixtures_only)
    version = (
        LessonVersion.objects.select_related(
            "lesson__series", "source_part__manifest__answer", "category", "series_version"
        )
        .filter(pk=_uuid(lesson_version_id))
        .first()
    )
    if version is None or version.source_part_id is None:
        raise cases.CaseConflict("lesson_source_unavailable")
    with _scope(
        subject_id,
        provider,
        synthetic_fixtures_only,
        [case_id, version.lesson.series.case_id],
        projection=True,
    ) as (locked, guard):
        _lesson(version, locked, guard)
        owner = locked[version.lesson.series.case_id]
        guard.permit(
            owner, owner, "READ_MEDIA", "LESSON", version.source_part_id, version.source_part.sha256
        )
        raw = media.raw_for_part(version.source_part)
        if sha256(raw).hexdigest() != version.source_snapshot["sha256"]:
            raise cases.CaseConflict("lesson_source_changed")
        return {
            "raw": raw,
            "media_type": version.source_part.media_type,
            "filename": version.source_part.filename,
            "sha256": version.source_part.sha256,
            "_guard": guard,
        }


@mutation_service
def search(
    *,
    subject_id,
    provider,
    query="",
    series_id="",
    lesson_id="",
    category_id="",
    relation_kind="",
    related_case_ref="",
    synthetic_fixtures_only=False,
):
    query = _text(query, 200, optional=True)
    if relation_kind not in {"", *KINDS} or (related_case_ref and not _ref(related_case_ref)):
        raise cases.CaseConflict("scholarly_search_invalid")
    for value in (series_id, lesson_id, category_id):
        if value:
            _uuid(value)
    with _scope(subject_id, provider, synthetic_fixtures_only, projection=True) as (locked, guard):
        catalog, lessons = _catalog(locked, guard)
        allowed_lessons = {row["id"]: row for row in lessons}
        category_choices = {(row["category_id"], row["category"]) for row in lessons}
        series_choices = {row["id"] for row in catalog}
        active_lessons = {key: [] for key in locked}
        # Approved historical links remain searchable if a later lesson version
        # has different classification or is not currently readable.
        for link in CaseLessonLink.objects.filter(case_id__in=locked):
            item = _link_projection(link, locked[link.case_id], locked, guard)
            if item is None or item["state"] != "APPROVE":
                continue
            active_lessons[link.case_id].append(item)
            lesson = item["lesson"]
            category_choices.add((lesson["category_id"], lesson["category"]))
            if lesson["id"] not in allowed_lessons:
                lessons.append(lesson)
                allowed_lessons[lesson["id"]] = lesson
            if lesson["series_id"] not in series_choices:
                catalog.append({"id": lesson["series_id"], "title": lesson["series_title"]})
                series_choices.add(lesson["series_id"])
        if lesson_id and str(_uuid(lesson_id)) not in allowed_lessons:
            raise cases.CaseConflict("lesson_filter_unavailable")
        if series_id and str(_uuid(series_id)) not in {row["id"] for row in catalog}:
            raise cases.CaseConflict("lesson_filter_unavailable")
        if category_id and str(_uuid(category_id)) not in {row[0] for row in category_choices}:
            raise cases.CaseConflict("lesson_filter_unavailable")
        if related_case_ref and related_case_ref not in {row.public_ref for row in locked.values()}:
            raise cases.CaseConflict("scholarly_case_unavailable")
        text = normalize_editorial_search(query)
        found = []
        for current in locked.values():
            latest = current.answers.order_by("-revision").first()
            haystack = normalize_editorial_search(
                " ".join(
                    [
                        current.public_ref,
                        current.source.original_question,
                        latest.text if latest else "",
                    ]
                )
            )
            if text and text not in haystack:
                continue
            matched_lessons, matched_relations = [], []
            for item in active_lessons[current.pk]:
                lesson = item["lesson"]
                if series_id and lesson["series_id"] != str(_uuid(series_id)):
                    continue
                if lesson_id and lesson["id"] != str(_uuid(lesson_id)):
                    continue
                if category_id and lesson["category_id"] != str(_uuid(category_id)):
                    continue
                matched_lessons.append(item)
            from django.db.models import Q

            for link in CaseRelation.objects.filter(
                Q(source_case=current) | Q(target_case=current)
            ):
                item = _link_projection(link, current, locked, guard)
                if item is None or item["state"] != "APPROVE":
                    continue
                if relation_kind and item["kind"] != relation_kind:
                    continue
                other = item["target_case_ref"] if item["outgoing"] else item["source_case_ref"]
                if related_case_ref and other != related_case_ref:
                    continue
                matched_relations.append(item)
            if (series_id or lesson_id or category_id) and not matched_lessons:
                continue
            if (relation_kind or related_case_ref) and not matched_relations:
                continue
            found.append(
                {
                    "case_ref": current.public_ref,
                    "stage": current.stage,
                    "lesson_matches": matched_lessons,
                    "relation_matches": matched_relations,
                }
            )
        return {
            "rows": sorted(found, key=lambda row: row["case_ref"]),
            "total": len(found),
            "series": catalog,
            "lessons": lessons,
            "categories": sorted(category_choices, key=lambda row: row[1]),
            "case_choices": sorted(row.public_ref for row in locked.values()),
            "filters": dict(
                query=query,
                series_id=series_id,
                lesson_id=lesson_id,
                category_id=category_id,
                relation_kind=relation_kind,
                related_case_ref=related_case_ref,
            ),
            "_guard": guard,
        }


def projection_fingerprint(case_ids):
    """Private whole-collection watermark, including empty collections/phantoms.

    Call under a transaction holding all participating canonical case locks.
    Immutable row seals cover content; identities and newly appended rows cover
    decisions, classification, attribution, order and latest-version changes.
    It is a consistency check, never a source-rights or identity grant.
    """
    from django.db.models import Q

    if not connection.in_atomic_block:
        raise cases.CaseConflict("scholarly_locked_projection_required")
    ids = tuple(sorted({_uuid(value) for value in case_ids}))
    relation_filter = Q(source_case_id__in=ids) | Q(target_case_id__in=ids)
    lesson_filter = Q(case_id__in=ids) | Q(lesson_version__lesson__series__case_id__in=ids)
    relations = CaseRelation.objects.filter(relation_filter)
    links = CaseLessonLink.objects.filter(lesson_filter)
    queries = (
        (
            Case.objects.filter(pk__in=ids),
            ("id", "revision", "evidence_version", "answer_revision", "approved_answer_id"),
        ),
        (LessonCategory.objects.filter(case_id__in=ids), ("id", "sha256")),
        (LessonSeries.objects.filter(case_id__in=ids), ("id", "public_id", "case_id")),
        (SeriesVersion.objects.filter(series__case_id__in=ids), ("id", "sha256")),
        (Lesson.objects.filter(series__case_id__in=ids), ("id", "public_id", "series_id")),
        (LessonVersion.objects.filter(lesson__series__case_id__in=ids), ("id", "sha256")),
        (relations, ("id", "sha256")),
        (links, ("id", "sha256")),
        (
            LinkDecision.objects.filter(Q(relation__in=relations) | Q(lesson_link__in=links)),
            ("id", "sha256"),
        ),
    )
    values = []
    for query, names in queries:
        values.append(
            [
                [str(value) if isinstance(value, uuid.UUID) else value for value in row]
                for row in query.order_by("id").values_list(*names)
            ]
        )
    return sha256(_json(values).encode()).hexdigest()


def approved_candidates_for_locked_case(*, case, answer_id):
    """Internal candidates for a separately authorized publication adapter.

    This is NOT a public projection and grants no permission. The caller must
    own a database transaction and canonical locks for this case and every
    emitted endpoint/lesson source case, in UUID order. It must independently
    recheck current actor scope, READ_LINK / READ_LESSON, exact publication
    grants for both relation endpoints, and an explicit expiring release of
    each curated lesson version. Candidate IDs and teacher keys stay internal.
    Private titles, source bytes, provenance and review notes are not returned.
    """
    from django.db.models import Q

    _enabled()
    if not connection.in_atomic_block:
        raise cases.CaseConflict("scholarly_locked_projection_required")
    answer = AnswerRevision.objects.filter(pk=_uuid(answer_id), case=case).first()
    if answer is None or answer.text_sha256 != cases._digest(answer.text):
        raise cases.CaseConflict("scholarly_answer_required")
    relations, lessons = [], []
    rows = CaseRelation.objects.filter(
        Q(source_case=case, source_answer=answer) | Q(target_case=case, target_answer=answer)
    ).order_by("id")
    for row in rows:
        state, history = _verify_link(row)
        if state != "APPROVE":
            continue
        relations.append(
            {
                "id": str(row.pk),
                "sha256": row.sha256,
                "kind": row.kind,
                "direction": "OUTGOING" if row.source_case_id == case.pk else "INCOMING",
                "source_case_id": str(row.source_case_id),
                "source_answer_id": str(row.source_answer_id),
                "source_answer_sha256": row.source_answer_sha256,
                "target_case_id": str(row.target_case_id),
                "target_answer_id": str(row.target_answer_id),
                "target_answer_sha256": row.target_answer_sha256,
                "decision_id": str(history[-1].pk),
                "decision_sha256": history[-1].sha256,
            }
        )
    for row in CaseLessonLink.objects.filter(case=case, answer=answer).order_by("id"):
        state, history = _verify_link(row)
        if state != "APPROVE":
            continue
        version = _verified(row.lesson_version)
        series_version = _verified(version.series_version)
        _verified(version.category)
        if version.source_part_id:
            if _source_snapshot(version.source_part) != version.source_snapshot:
                raise cases.CaseConflict("lesson_source_changed")
        elif version.source_snapshot:
            raise cases.CaseConflict("lesson_source_changed")
        lessons.append(
            {
                "link_id": str(row.pk),
                "link_sha256": row.sha256,
                "answer_id": str(row.answer_id),
                "answer_sha256": row.answer_sha256,
                "lesson_id": str(version.lesson_id),
                "lesson_public_id": str(version.lesson.public_id),
                "lesson_version_id": str(version.pk),
                "lesson_version": version.number,
                "lesson_sha256": version.sha256,
                "series_public_id": str(version.lesson.series.public_id),
                "series_version_id": str(series_version.pk),
                "series_sha256": series_version.sha256,
                "owner_case_id": str(version.lesson.series.case_id),
                "teacher_keys": [
                    {"provider_id": teacher["provider_id"], "subject_id": teacher["subject_id"]}
                    for teacher in series_version.teachers
                    if "subject_id" in teacher
                ],
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "decision_id": str(history[-1].pk),
                "decision_sha256": history[-1].sha256,
            }
        )
    return {"relations": relations, "lessons": lessons}
