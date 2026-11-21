"""Human priority and primary assignment under exact current operational grants."""

import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from django.conf import settings

from apps.case_assignments import coordination as persistence
from apps.case_assignments import services as assignments
from apps.casework import services as cases
from apps.mufti_review.identity import _ref, validate_identity

from . import identity
from .boundary import digest, epoch, scope


@dataclass(frozen=True)
class PriorityOption:
    value: str
    label: str
    rank: int


def resource(case, **values):
    return {"kind": "CASE_COORDINATION", "case_id": str(case.pk), **values}


def available(case, guard):
    return guard.coordination_feature and guard.permit_resource(
        case, "READ_COORDINATION", resource(case)
    )


def summary(case, guard):
    events, primary, participants = assignments._read(case, guard.provider_id)
    priority = persistence.priority_projection(persistence.priority_rows(case, guard.provider_id))
    return {
        "public_ref": case.public_ref,
        "primary": primary,
        "priority": priority["label"],
        "rank": priority["rank"] if priority["rank"] is not None else 101,
    }


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.coordination_feature:
        raise cases.CaseConflict("operational_coordination_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_coordination_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    guard.permit_resource(case, "READ_COORDINATION", resource(case), required=True)
    cases._verify(case)
    return case


class CoordinationPolicy:
    """Pin configured finite selectors and independently resolve each target Mufti.

    A candidate list only supplies choices; each action still needs its own
    exact resource grant. Assignment cannot create or broaden a target's scope.
    """

    def __init__(self, guard, case):
        self.guard, self.case = guard, case
        self.candidates = getattr(settings, "FATWA_CASE_ASSIGNMENT_CANDIDATES", None)
        self.priorities = getattr(settings, "FATWA_OPERATIONAL_PRIORITY_POLICY", None)
        if not callable(self.candidates) or not callable(self.priorities):
            raise cases.CaseConflict("coordination_explicit_policy_required")
        self.candidate_epoch, self.priority_epoch = epoch(self.candidates), epoch(self.priorities)
        self.targets, self.options = self.read()
        self.before = self.pin(self.targets, self.options)
        self.policy_sha256 = digest(
            {"epoch": self.priority_epoch, "options": [asdict(x) for x in self.options]}
        )
        guard.adapters.append(self)

    def read(self):
        try:
            # This is the existing assignment selector contract; preserve its
            # subject-id argument for both Mufti and operational callers.
            selected = self.candidates(self.guard.actor.subject_id, self.case.public_ref)
            options = self.priorities(self.guard.actor, self.case.public_ref)
            if (
                type(selected) not in (list, tuple)
                or len(selected) > 64
                or any(not _ref(value) for value in selected)
                or len(selected) != len(set(selected))
                or type(options) not in (list, tuple)
                or not 1 <= len(options) <= 16
            ):
                raise ValueError
            seen = set()
            for row in options:
                if (
                    type(row) is not PriorityOption
                    or not _ref(row.value, 64)
                    or type(row.label) is not str
                    or not 1 <= len(row.label) <= 128
                    or not row.label.strip()
                    or "\x00" in row.label
                    or type(row.rank) is not int
                    or not 0 <= row.rank <= 100
                    or row.value in seen
                ):
                    raise ValueError
                seen.add(row.value)
            targets = {}
            for subject in selected:
                actor = self.guard.directory.resolve(subject)
                validate_identity(actor, subject_id=subject, case_key=self.case.public_ref)
                targets[subject] = actor
                self.guard.deadline = min(self.guard.deadline, actor.valid_until)
            return targets, tuple(options)
        except Exception as exc:
            raise cases.CaseConflict("coordination_policy_unavailable") from exc

    @staticmethod
    def pin(targets, options):
        return (
            tuple(sorted((key, identity.pin(value)) for key, value in targets.items())),
            options,
        )

    def callbacks(self):
        targets, options = self.read()
        if self.pin(targets, options) != self.before:
            raise cases.CaseConflict("coordination_choices_changed")

    def final_pins(self):
        if (
            getattr(settings, "FATWA_CASE_ASSIGNMENT_CANDIDATES", None) is not self.candidates
            or getattr(settings, "FATWA_OPERATIONAL_PRIORITY_POLICY", None) is not self.priorities
            or epoch(self.candidates) != self.candidate_epoch
            or epoch(self.priorities) != self.priority_epoch
        ):
            raise cases.CaseConflict("coordination_policy_changed")


def priority_resource(case, policy, option):
    return resource(
        case,
        priority=option.value,
        label=option.label,
        rank=option.rank,
        policy_sha256=policy.policy_sha256,
    )


def _projection(case, guard, policy, *, saved=False):
    events, primary, participants = assignments._read(case, guard.provider_id)
    assignment = assignments._projection(events, primary, participants, guard.actor, ())
    priority = persistence.priority_projection(persistence.priority_rows(case, guard.provider_id))
    choices = [
        {"subject": subject, "epoch": target.auth_epoch}
        for subject, target in sorted(policy.targets.items())
        if subject != primary
        and guard.permit_resource(
            case, "SET_PRIMARY", resource(case, target=subject, target_epoch=target.auth_epoch)
        )
    ]
    options = [
        asdict(option)
        for option in policy.options
        if guard.permit_resource(case, "SET_PRIORITY", priority_resource(case, policy, option))
    ]
    return {
        "public_ref": case.public_ref,
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "command_id": str(uuid.uuid4()),
        "assignment": assignment,
        "priority": priority,
        "targets": choices,
        "priority_options": options,
        "policy_sha256": policy.policy_sha256,
        "can_clear": bool(
            primary and guard.permit_resource(case, "CLEAR_PRIMARY", resource(case, target=primary))
        ),
        "saved": saved,
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        policy = CoordinationPolicy(guard, case)
        yield _projection(case, guard, policy)


@contextmanager
def assign(
    *,
    case_ref,
    action,
    target_subject,
    target_epoch,
    reason,
    confirmed,
    command_id,
    expected_version,
    expected_revision,
    expected_evidence_version,
    **common,
):
    if confirmed is not True or action not in {"SET_PRIMARY", "CLEAR_PRIMARY"}:
        raise cases.CaseConflict("coordination_confirmation_required")
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        policy = CoordinationPolicy(guard, case)
        target = policy.targets.get(target_subject) if action == "SET_PRIMARY" else None
        if action == "SET_PRIMARY":
            if target is None or target.auth_epoch != target_epoch:
                raise cases.CaseConflict("coordination_target_changed")
            values = resource(case, target=target_subject, target_epoch=target.auth_epoch)
        else:
            if target_epoch != "":
                raise cases.CaseConflict("coordination_clear_target_invalid")
            values = resource(case, target=target_subject)
        guard.permit_resource(case, action, values, required=True)
        guard.finish()
        row, created = persistence._append_assignment_locked(
            case=case,
            actor=guard.actor,
            provider_id=guard.provider_id,
            action=action,
            target_subject=target_subject,
            target_actor=target,
            reason=reason,
            command_id=command_id,
            expected_version=expected_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )
        if created:
            guard.account_for_append(row)
        yield _projection(case, guard, policy, saved=True)


@contextmanager
def set_priority(
    *,
    case_ref,
    value,
    policy_sha256,
    reason,
    confirmed,
    command_id,
    expected_version,
    expected_revision,
    expected_evidence_version,
    **common,
):
    if confirmed is not True:
        raise cases.CaseConflict("coordination_confirmation_required")
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        policy = CoordinationPolicy(guard, case)
        option = next((row for row in policy.options if row.value == value), None)
        if option is None or policy_sha256 != policy.policy_sha256:
            raise cases.CaseConflict("coordination_priority_changed")
        guard.permit_resource(
            case, "SET_PRIORITY", priority_resource(case, policy, option), required=True
        )
        guard.finish()
        row, created = persistence._append_priority_locked(
            case=case,
            actor=guard.actor,
            provider_id=guard.provider_id,
            value=option.value,
            label=option.label,
            rank=option.rank,
            policy_sha256=policy.policy_sha256,
            reason=reason,
            command_id=command_id,
            expected_version=expected_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )
        if created:
            guard.account_for_append(row)
        yield _projection(case, guard, policy, saved=True)
