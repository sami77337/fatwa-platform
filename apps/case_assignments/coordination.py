"""Locked persistence for explicitly authorized human administrative coordination.

These private primitives confer no authority. The operational caller owns current
identity/action/resource grants and the canonical lock through final rendering.
The existing public Mufti assignment services retain their original action set.
"""

from hashlib import sha256

from django.db import connection

from apps.casework import services as cases
from apps.mufti_review.identity import MuftiIdentity, _ref, validate_identity
from apps.operational_workspace import identity

from . import services
from .models import ADMIN_ACTIONS, AssignmentEvent, PriorityEvent


def _text(value, maximum):
    cases._text(value)
    if len(value) > maximum:
        raise cases.CaseConflict("coordination_text_invalid")


def _actor(case, actor, provider_id):
    if not connection.in_atomic_block or not _ref(provider_id):
        raise cases.CaseConflict("coordination_locked_boundary_required")
    identity.validate(actor, case_ref=case.public_ref)
    cases._verify(case)


def _version(value):
    if type(value) is not int or not 0 <= value < services.MAX_EVENTS:
        raise cases.CaseConflict("coordination_version_invalid")


def _assignment_same(
    row, *, actor, provider_id, action, target_subject, reason, revision, evidence
):
    return (
        row.subject_id,
        row.actor_role,
        row.provider_id,
        row.auth_epoch,
        row.action,
        row.target_subject,
        row.reason,
        row.case_revision,
        row.evidence_version,
    ) == (
        actor.subject_id,
        actor.role,
        provider_id,
        actor.auth_epoch,
        action,
        target_subject,
        reason,
        revision,
        evidence,
    )


def _append_assignment_locked(
    *,
    case,
    actor,
    provider_id,
    action,
    target_subject,
    target_actor,
    reason,
    command_id,
    expected_version,
    expected_revision,
    expected_evidence_version,
):
    _actor(case, actor, provider_id)
    _text(reason, 2000)
    _version(expected_version)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    command = cases._uuid(command_id)
    if action not in ADMIN_ACTIONS or not _ref(target_subject):
        raise cases.CaseConflict("coordination_assignment_invalid")
    if action == "SET_PRIMARY":
        try:
            validate_identity(target_actor, case_key=case.public_ref)
        except Exception as exc:
            raise cases.CaseConflict("coordination_target_unavailable") from exc
        if type(target_actor) is not MuftiIdentity or target_actor.subject_id != target_subject:
            raise cases.CaseConflict("coordination_target_unavailable")
    elif target_actor is not None:
        raise cases.CaseConflict("coordination_clear_target_invalid")
    events, primary, participants = services._read(case, provider_id)
    previous = next((row for row in events if row.command_id == command), None)
    if previous is not None:
        if previous.sequence != expected_version + 1 or not _assignment_same(
            previous,
            actor=actor,
            provider_id=provider_id,
            action=action,
            target_subject=target_subject,
            reason=reason,
            revision=expected_revision,
            evidence=expected_evidence_version,
        ):
            raise cases.CaseConflict("coordination_command_reused")
        return previous, False
    cases._versions(case, expected_revision, expected_evidence_version)
    if len(events) != expected_version:
        raise cases.CaseConflict("assignment_version_changed")
    services._transition(primary, participants, action, actor.subject_id, target_subject)
    row = AssignmentEvent(
        case=case,
        sequence=len(events) + 1,
        action=action,
        target_subject=target_subject,
        subject_id=actor.subject_id,
        actor_role=actor.role,
        provider_id=provider_id,
        auth_epoch=actor.auth_epoch,
        reason=reason,
        command_id=command,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        previous_sha256=events[-1].sha256 if events else services.ZERO_HASH,
    )
    row.sha256 = services._digest(row)
    row.save(force_insert=True)
    row.refresh_from_db()
    return row, True


def priority_digest(row):
    values = [
        str(getattr(row, key))
        for key in (
            "case_id",
            "sequence",
            "value",
            "rank",
            "policy_sha256",
            "command_id",
            "subject_id",
            "actor_role",
            "provider_id",
            "auth_epoch",
            "case_revision",
            "evidence_version",
            "previous_sha256",
        )
    ]
    values.extend(sha256(getattr(row, key).encode()).hexdigest() for key in ("label", "reason"))
    return sha256("|".join(values).encode()).hexdigest()


def priority_rows(case, provider_id):
    rows = list(PriorityEvent.objects.filter(case=case).order_by("sequence")[:257])
    if len(rows) > services.MAX_EVENTS:
        raise cases.CaseConflict("priority_history_limit")
    previous = services.ZERO_HASH
    for number, row in enumerate(rows, 1):
        if (
            row.sequence != number
            or row.previous_sha256 != previous
            or row.sha256 != priority_digest(row)
            or row.provider_id != provider_id
            or row.case_revision > case.revision
            or row.evidence_version > case.evidence_version
        ):
            raise cases.CaseConflict("priority_history_invalid")
        previous = row.sha256
    return rows


def priority_projection(rows):
    latest = rows[-1] if rows else None
    return {
        "version": len(rows),
        "value": latest.value if latest else None,
        "label": latest.label if latest else "لم تُحدّد أولوية بشرية",
        "rank": latest.rank if latest else None,
        "history": [
            {
                "sequence": row.sequence,
                "value": row.value,
                "label": row.label,
                "rank": row.rank,
                "reason": row.reason,
                "actor": row.subject_id,
                "actor_role": row.actor_role,
                "created_at": row.created_at,
            }
            for row in reversed(rows)
        ],
    }


def _append_priority_locked(
    *,
    case,
    actor,
    provider_id,
    value,
    label,
    rank,
    policy_sha256,
    reason,
    command_id,
    expected_version,
    expected_revision,
    expected_evidence_version,
):
    _actor(case, actor, provider_id)
    _text(reason, 2000)
    _text(label, 128)
    _version(expected_version)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    command = cases._uuid(command_id)
    if (
        not _ref(value, 64)
        or type(rank) is not int
        or not 0 <= rank <= 100
        or type(policy_sha256) is not str
        or len(policy_sha256) != 64
        or any(c not in "0123456789abcdef" for c in policy_sha256)
    ):
        raise cases.CaseConflict("priority_option_invalid")
    rows = priority_rows(case, provider_id)
    previous = next((row for row in rows if row.command_id == command), None)
    expected = (
        actor.subject_id,
        actor.role,
        provider_id,
        actor.auth_epoch,
        value,
        label,
        rank,
        policy_sha256,
        reason,
        expected_revision,
        expected_evidence_version,
    )
    if previous is not None:
        observed = (
            previous.subject_id,
            previous.actor_role,
            previous.provider_id,
            previous.auth_epoch,
            previous.value,
            previous.label,
            previous.rank,
            previous.policy_sha256,
            previous.reason,
            previous.case_revision,
            previous.evidence_version,
        )
        if previous.sequence != expected_version + 1 or observed != expected:
            raise cases.CaseConflict("coordination_command_reused")
        return previous, False
    cases._versions(case, expected_revision, expected_evidence_version)
    if len(rows) != expected_version:
        raise cases.CaseConflict("priority_version_changed")
    if rows and (rows[-1].value, rows[-1].label, rows[-1].rank, rows[-1].policy_sha256) == (
        value,
        label,
        rank,
        policy_sha256,
    ):
        raise cases.CaseConflict("priority_already_current")
    row = PriorityEvent(
        case=case,
        sequence=len(rows) + 1,
        value=value,
        label=label,
        rank=rank,
        policy_sha256=policy_sha256,
        reason=reason,
        command_id=command,
        subject_id=actor.subject_id,
        actor_role=actor.role,
        provider_id=provider_id,
        auth_epoch=actor.auth_epoch,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        previous_sha256=rows[-1].sha256 if rows else services.ZERO_HASH,
    )
    row.sha256 = priority_digest(row)
    row.save(force_insert=True)
    row.refresh_from_db()
    return row, True
