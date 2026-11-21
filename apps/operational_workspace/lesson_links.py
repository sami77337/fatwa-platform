"""Operational lesson links use actual actors and existing immutable scholarly journals."""

import uuid
from contextlib import contextmanager

from django.conf import settings

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.scholarly_links import services as links
from apps.scholarly_links.authority import ScholarlyAuthority
from apps.scholarly_links.models import CaseLessonLink, Lesson, LessonVersion

from .boundary import scope

ACTION_MAP = {
    "READ_LESSON": "READ_OPERATIONAL_LESSON",
    "READ_LINK": "READ_LESSON_LINK",
    "PROPOSE": "PROPOSE_LESSON_LINK",
    "APPROVE": "APPROVE_LESSON_LINK",
    "REJECT": "REJECT_LESSON_LINK",
    "WITHDRAW": "WITHDRAW_LESSON_LINK",
}


def resource(source, target, version, link=None):
    result = {
        "kind": "CASE_LESSON_LINK" if link is not None else "CASE_LESSON_VERSION",
        "case_id": str(source.pk),
        "target_case_id": str(target.pk),
        "version_id": str(version.pk),
        "version_sha256": version.sha256,
    }
    if link is not None:
        result.update(link_id=str(link.pk), link_sha256=link.sha256)
    return result


class LessonBridge:
    def __init__(self, guard):
        links._enabled()
        self.guard, self.provider, self.actor = guard, guard.provider, guard.actor
        self.provider_id, self.locked = guard.provider_id, guard.locked
        self.policy = getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None)
        if not isinstance(self.policy, ScholarlyAuthority):
            raise cases.CaseConflict("operational_lesson_authority_required")
        self.epoch = self.policy_epoch()
        self.media_flag = getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False)
        self.checks, self.part_pins = [], {}
        guard.adapters.append(self)

    def policy_epoch(self):
        try:
            value = self.policy.projection_epoch()
        except Exception as exc:
            raise cases.CaseConflict("operational_lesson_policy_unavailable") from exc
        if type(value) is not str or not 1 <= len(value) <= 131072:
            raise cases.CaseConflict("operational_lesson_policy_unavailable")
        return value

    def _resource(self, source, target, action, identifier, sha256):
        if action in {"READ_LESSON", "PROPOSE"}:
            version = (
                LessonVersion.objects.select_related("lesson__series")
                .filter(
                    pk=cases._uuid(identifier),
                    lesson__series__case=target,
                )
                .first()
            )
            if version is None or version.sha256 != sha256:
                raise cases.CaseConflict("operational_lesson_source_changed")
            return resource(source, target, version)
        link = (
            CaseLessonLink.objects.select_related("lesson_version__lesson__series")
            .filter(
                pk=cases._uuid(identifier),
                case=source,
                lesson_version__lesson__series__case=target,
            )
            .first()
        )
        if link is None or link.sha256 != sha256:
            raise cases.CaseConflict("operational_lesson_source_changed")
        return resource(source, target, link.lesson_version, link)

    def permit(
        self, source, target, action, kind, resource_id="", resource_sha256="", *, required=True
    ):
        if (
            action not in ACTION_MAP
            or kind != "LESSON"
            or source.pk not in self.locked
            or target.pk not in self.locked
        ):
            if required:
                raise cases.CaseConflict("operational_lesson_action_unavailable")
            return False
        for case in (source, target):
            if not self.guard.permit(case, "READ_CASE", "case", required=required):
                return False
        value = self._resource(source, target, action, resource_id, resource_sha256)
        if not self.guard.permit_resource(source, ACTION_MAP[action], value, required=required):
            return False
        arguments = dict(
            provider_id=self.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=source.public_ref,
            target_case_ref=target.public_ref,
            action=action,
            kind="LESSON",
            resource_id=str(resource_id),
            resource_sha256=resource_sha256,
        )
        allowed = self.call(arguments)
        self.checks.append((arguments, allowed))
        if required and not allowed:
            raise cases.CaseConflict("operational_lesson_action_denied")
        return allowed

    def call(self, arguments):
        try:
            return self.policy.permits(**arguments) is True
        except Exception as exc:
            raise cases.CaseConflict("operational_lesson_policy_unavailable") from exc

    def callbacks(self):
        for arguments, allowed in self.checks:
            if self.call(arguments) != allowed:
                raise cases.CaseConflict("operational_lesson_grant_changed")

    def final_pins(self):
        links._enabled()
        if (
            getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None) is not self.policy
            or self.policy_epoch() != self.epoch
            or getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False) is not self.media_flag
        ):
            raise cases.CaseConflict("operational_lesson_policy_changed")
        for part_id, expected in self.part_pins.items():
            part = AnswerPart.objects.select_related("manifest__answer").filter(pk=part_id).first()
            if part is None or links._source_snapshot(part) != expected:
                raise cases.CaseConflict("operational_lesson_source_changed")


def available(case, guard):
    return guard.lesson_feature and guard.permit(case, "READ_LESSON_LINKS", "lesson_links")


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.lesson_feature:
        raise cases.CaseConflict("operational_lesson_links_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_lesson_links_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    guard.permit(case, "READ_LESSON_LINKS", "lesson_links", required=True)
    cases._verify(case)
    return case


def _canonical(case):
    answer = links._answer(case)
    if case.stage != "ANSWERED" or answer.pk != case.approved_answer_id:
        raise cases.CaseConflict("operational_lesson_approved_answer_required")
    return answer


def _version(identifier, guard):
    row = (
        LessonVersion.objects.select_related(
            "lesson__series",
            "source_part__manifest__answer",
            "series_version",
            "category",
        )
        .filter(pk=cases._uuid(identifier), lesson__series__case_id__in=guard.locked)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("operational_lesson_unavailable")
    return row


def _projection(case, guard, bridge, *, saved=False):
    lessons = list(Lesson.objects.filter(series__case_id__in=guard.locked).order_by("pk")[:65])
    if len(lessons) > 64:
        raise cases.CaseConflict("operational_lesson_catalog_bound")
    catalog = []
    for lesson in lessons:
        version = _version(links._latest(LessonVersion, "lesson", lesson).pk, guard)
        target = guard.locked[version.lesson.series.case_id]
        dto = links._lesson(version, guard.locked, bridge, required=False)
        if dto is None:
            continue
        dto.update(
            target_revision=target.revision,
            target_evidence_version=target.evidence_version,
            can_propose=bool(
                case.stage == "ANSWERED"
                and case.approved_answer_id
                and bridge.permit(
                    case, target, "PROPOSE", "LESSON", version.pk, version.sha256, required=False
                )
            ),
        )
        catalog.append(dto)
    records = list(
        CaseLessonLink.objects.filter(case=case)
        .select_related(
            "lesson_version__lesson__series",
            "answer",
        )
        .order_by("created_at", "pk")[:129]
    )
    if len(records) > 128:
        raise cases.CaseConflict("operational_lesson_history_bound")
    related = []
    for record in records:
        dto = links._link_projection(record, case, guard.locked, bridge)
        if dto is None:
            continue
        dto["current"] = (
            record.answer_id == case.approved_answer_id
            and record.evidence_version == case.evidence_version
        )
        dto["can_approve"] = dto["can_approve"] and dto["current"]
        related.append(dto)
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "catalog": catalog,
        "links": related,
        "command_id": str(uuid.uuid4()),
        "saved": saved,
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = LessonBridge(guard)
        yield _projection(case, guard, bridge)


@contextmanager
def propose(
    *,
    case_ref,
    lesson_version_id,
    lesson_sha256,
    reason,
    command_id,
    expected_revision,
    expected_evidence_version,
    expected_target_revision,
    expected_target_evidence_version,
    start_ms=None,
    end_ms=None,
    **common,
):
    reason = links._text(reason, 1000)
    command = cases._uuid(command_id)
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = LessonBridge(guard)
        version = _version(lesson_version_id, guard)
        target = guard.locked[version.lesson.series.case_id]
        links._pins(case, expected_revision, expected_evidence_version)
        links._pins(target, expected_target_revision, expected_target_evidence_version)
        if version.sha256 != lesson_sha256:
            raise cases.CaseConflict("operational_lesson_source_changed")
        links._lesson(version, guard.locked, bridge)
        links._span(version, start_ms, end_ms)
        bridge.permit(case, target, "PROPOSE", "LESSON", version.pk, version.sha256)
        answer = _canonical(case)
        guard.finish()
        row, created = links._append_lesson_link_locked(
            source=case,
            target=target,
            version=version,
            answer=answer,
            guard=bridge,
            reason=reason,
            command_id=command,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if created:
            guard.account_for_append(row)
        yield _projection(case, guard, bridge, saved=True)


@contextmanager
def decide(
    *,
    case_ref,
    link_id,
    link_sha256,
    action,
    note,
    confirmed,
    command_id,
    expected_sequence,
    expected_revision,
    expected_evidence_version,
    expected_target_revision,
    expected_target_evidence_version,
    **common,
):
    if action not in {"APPROVE", "REJECT", "WITHDRAW"} or confirmed is not True:
        raise cases.CaseConflict("operational_lesson_confirmation_required")
    note = links._text(note, 1000)
    command = cases._uuid(command_id)
    links._integer(expected_sequence, zero=True)
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = LessonBridge(guard)
        link = (
            CaseLessonLink.objects.select_related("lesson_version__lesson__series")
            .filter(
                pk=cases._uuid(link_id),
                case=case,
                lesson_version__lesson__series__case_id__in=guard.locked,
            )
            .first()
        )
        if link is None or link.sha256 != link_sha256:
            raise cases.CaseConflict("operational_lesson_link_unavailable")
        target = guard.locked[link.lesson_version.lesson.series.case_id]
        links._pins(case, expected_revision, expected_evidence_version)
        links._pins(target, expected_target_revision, expected_target_evidence_version)
        bridge.permit(case, target, "READ_LINK", "LESSON", link.pk, link.sha256)
        bridge.permit(case, target, action, "LESSON", link.pk, link.sha256)
        links._lesson(link.lesson_version, guard.locked, bridge)
        if action == "APPROVE" and _canonical(case).pk != link.answer_id:
            raise cases.CaseConflict("operational_lesson_answer_changed")
        guard.finish()
        row, created = links._append_link_decision_locked(
            source=case,
            target=target,
            link=link,
            action=action,
            note=note,
            command_id=command,
            expected_sequence=expected_sequence,
            guard=bridge,
        )
        if created:
            guard.account_for_append(row)
        yield _projection(case, guard, bridge, saved=True)
