"""Explicit human coordination inside existing scoped MUFTI authority.

Assignment never grants access, reserves exclusive edit rights, changes facts,
invalidates an answer, or approves a ruling. The canonical case row lock serializes
coordination writes; its revision and evidence version are observed, not changed.
"""

import hashlib

from django.conf import settings

from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable, _ref, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .models import ACTIONS, AssignmentEvent

MAX_EVENTS = 256
MAX_PARTICIPANTS = 16
ZERO_HASH = "0" * 64
LABELS = {
    "CLAIM": "تولى القضية بصفته المفتي الأساسي",
    "RELEASE": "أعاد القضية إلى القائمة المشتركة",
    "TRANSFER": "نقل مسؤولية المفتي الأساسي",
    "ADD_CONTRIBUTOR": "سجل مفتيًا مساهمًا",
    "ADD_REVIEWER": "سجل مفتيًا مراجعًا",
    "REMOVE_PARTICIPANT": "أنهى المشاركة التنسيقية",
}


def _enabled():
    if getattr(settings, "FATWA_CASE_ASSIGNMENTS_ENABLED", False) is not True:
        raise cases.CaseConflict("case_assignments_disabled")


def _digest(event):
    payload = "|".join(
        str(getattr(event, name))
        for name in (
            "case_id",
            "sequence",
            "action",
            "target_subject",
            "subject_id",
            "provider_id",
            "auth_epoch",
            "case_revision",
            "evidence_version",
            "previous_sha256",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _transition(primary, participants, action, actor, target):
    participants = dict(participants)
    if action == "CLAIM":
        if primary is not None or target != actor:
            raise cases.CaseConflict("assignment_claim_unavailable")
        primary = actor
        participants.pop(actor, None)
    elif action == "RELEASE":
        if primary != actor or target != actor:
            raise cases.CaseConflict("assignment_release_unavailable")
        primary = None
    elif action == "TRANSFER":
        if primary != actor or target == actor:
            raise cases.CaseConflict("assignment_transfer_unavailable")
        primary = target
        participants.pop(target, None)
    elif action in {"ADD_CONTRIBUTOR", "ADD_REVIEWER"}:
        role = "CONTRIBUTOR" if action == "ADD_CONTRIBUTOR" else "REVIEWER"
        if target == primary or (actor != primary and target != actor):
            raise cases.CaseConflict("assignment_participant_unavailable")
        if target not in participants and len(participants) >= MAX_PARTICIPANTS:
            raise cases.CaseConflict("assignment_participant_limit")
        if participants.get(target) == role:
            raise cases.CaseConflict("assignment_already_recorded")
        participants[target] = role
    elif action == "REMOVE_PARTICIPANT":
        if target not in participants or (actor != primary and target != actor):
            raise cases.CaseConflict("assignment_participant_unavailable")
        del participants[target]
    else:
        raise cases.CaseConflict("assignment_action_invalid")
    return primary, participants


def _read(case, provider_id):
    events = list(AssignmentEvent.objects.filter(case=case).order_by("sequence")[: MAX_EVENTS + 1])
    if len(events) > MAX_EVENTS:
        raise cases.CaseConflict("assignment_history_limit")
    primary, participants, previous = None, {}, ZERO_HASH
    for sequence, event in enumerate(events, start=1):
        if (
            event.sequence != sequence
            or event.previous_sha256 != previous
            or event.sha256 != _digest(event)
            or event.provider_id != provider_id
            or event.case_revision > case.revision
            or event.evidence_version > case.evidence_version
            or not all(
                _ref(value) for value in (event.subject_id, event.target_subject, event.provider_id)
            )
            or not _ref(event.auth_epoch, 64)
        ):
            raise cases.CaseConflict("assignment_history_invalid")
        primary, participants = _transition(
            primary,
            participants,
            event.action,
            event.subject_id,
            event.target_subject,
        )
        previous = event.sha256
    return events, primary, participants


def _same_actor(provider, actor, case, provider_id=None):
    current = cases._identity(provider, actor.subject_id, case)
    if (
        current.auth_epoch != actor.auth_epoch
        or current.case_keys != actor.case_keys
        or (provider_id is not None and provider.provider_id != provider_id)
    ):
        raise cases.CaseConflict("assignment_identity_changed")
    return current


def _candidates(case, actor, provider):
    """Server-owned, bounded choice list; the callback cannot manufacture authority.

    A configured callback returns subject IDs only. Each must independently resolve
    as an active MUFTI already scoped to this case in the trusted directory. A
    missing callback means self-coordination only, never an unrestricted directory.
    """
    resolver = getattr(settings, "FATWA_CASE_ASSIGNMENT_CANDIDATES", None)
    if resolver is None:
        return {}
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if not callable(resolver) or getattr(directory, "provider_id", None) != provider.provider_id:
        raise cases.CaseConflict("assignment_candidates_unavailable")
    try:
        values = resolver(actor.subject_id, case.public_ref)
        if type(values) not in (tuple, list) or len(values) > MAX_PARTICIPANTS:
            raise ValueError("invalid_candidates")
        if any(not _ref(value) for value in values) or len(values) != len(set(values)):
            raise ValueError("invalid_candidates")
        result = {}
        for subject in values:
            if subject != actor.subject_id:
                result[subject] = resolve_identity(directory, subject, case_key=case.public_ref)
        _same_actor(provider, actor, case)
        return result
    except (IdentityUnavailable, ValueError, TypeError) as exc:
        raise cases.CaseConflict("assignment_candidates_unavailable") from exc
    except Exception as exc:
        raise cases.CaseConflict("assignment_candidates_unavailable") from exc


def _projection(events, primary, participants, actor, candidates):
    return {
        "version": len(events),
        "primary_subject": primary,
        "is_primary": primary == actor.subject_id,
        "is_shared": primary is None,
        "is_mine": primary == actor.subject_id or actor.subject_id in participants,
        "subject_id": actor.subject_id,
        "my_role": "PRIMARY" if primary == actor.subject_id else participants.get(actor.subject_id),
        "participants": [
            {
                "subject_id": subject,
                "role": role,
                "label": "مساهم" if role == "CONTRIBUTOR" else "مراجع",
                "can_remove": actor.subject_id in {primary, subject},
            }
            for subject, role in sorted(participants.items())
        ],
        "candidates": sorted(candidates),
        "history": [
            {
                "sequence": event.sequence,
                "label": LABELS[event.action],
                "actor": event.subject_id,
                "target": event.target_subject,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@mutation_service
def read_assignment(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    expected_revision=None,
    expected_evidence_version=None,
    include_candidates=True,
):
    _enabled()
    provider_id = provider.provider_id
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        events, primary, participants = _read(case, provider_id)
        candidates = _candidates(case, actor, provider) if include_candidates else {}
        result = _projection(events, primary, participants, actor, candidates)
        result["approved_at"] = (
            case.decisions.filter(answer_id=case.approved_answer_id, action="APPROVE")
            .values_list("created_at", flat=True)
            .first()
            if case.approved_answer_id
            else None
        )
        _same_actor(provider, actor, case, provider_id)
        return result


@mutation_service
def annotate_queue(rows, *, subject_id, provider, synthetic_fixtures_only=False):
    """Hold batch locks through the final identity check; never expand input scope."""
    _enabled()
    cases._guard(synthetic_fixtures_only)
    provider_id = provider.provider_id
    try:
        initial = resolve_identity(provider, subject_id)
        with synthetic_queue_atomic():
            result = {}
            # All batch readers acquire shared canonical case locks in one order.
            # The final projection retains the caller's original display ordering.
            for row in sorted(rows, key=lambda item: item["case_id"]):
                assignment = read_assignment(
                    case_id=row["case_id"],
                    subject_id=subject_id,
                    provider=provider,
                    synthetic_fixtures_only=synthetic_fixtures_only,
                    expected_revision=row["revision"],
                    expected_evidence_version=row["evidence_version"],
                    include_candidates=False,
                )
                result[row["case_id"]] = {
                    **row,
                    "assignment": assignment,
                    "approved_at": assignment["approved_at"],
                }
            current = resolve_identity(provider, subject_id)
            if (
                provider.provider_id != provider_id
                or current.auth_epoch != initial.auth_epoch
                or current.case_keys != initial.case_keys
            ):
                raise cases.CaseConflict("assignment_identity_changed")
            return [result[row["case_id"]] for row in rows]
    except IdentityUnavailable as exc:
        raise cases.CaseConflict("assignment_identity_changed") from exc


@mutation_service
def change_assignment(
    *,
    case_id,
    subject_id,
    provider,
    action,
    expected_assignment_version,
    expected_revision,
    expected_evidence_version,
    target_subject=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    provider_id = provider.provider_id
    if (
        action not in ACTIONS
        or type(expected_assignment_version) is not int
        or not 0 <= expected_assignment_version <= MAX_EVENTS
    ):
        raise cases.CaseConflict("assignment_command_invalid")
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        target = actor.subject_id if action in {"CLAIM", "RELEASE"} else target_subject
        if not _ref(target) or (action in {"CLAIM", "RELEASE"} and target_subject is not None):
            raise cases.CaseConflict("assignment_target_invalid")
        events, primary, participants = _read(case, provider_id)
        if len(events) != expected_assignment_version:
            # An exact retry of the immediately preceding accepted command is a
            # read. Any intervening assignment/evidence change still conflicts.
            last = events[-1] if events else None
            if not (
                last
                and len(events) == expected_assignment_version + 1
                and (
                    last.action,
                    last.target_subject,
                    last.subject_id,
                    last.provider_id,
                    last.auth_epoch,
                    last.case_revision,
                    last.evidence_version,
                )
                == (
                    action,
                    target,
                    actor.subject_id,
                    provider.provider_id,
                    actor.auth_epoch,
                    case.revision,
                    case.evidence_version,
                )
            ):
                raise cases.CaseConflict("assignment_version_changed")
            _same_actor(provider, actor, case, provider_id)
            return _projection(events, primary, participants, actor, {})
        if len(events) >= MAX_EVENTS:
            raise cases.CaseConflict("assignment_history_limit")
        candidates = (
            _candidates(case, actor, provider)
            if target != actor.subject_id and action != "REMOVE_PARTICIPANT"
            else {}
        )
        if (
            target != actor.subject_id
            and action != "REMOVE_PARTICIPANT"
            and target not in candidates
        ):
            raise cases.CaseConflict("assignment_target_unavailable")
        next_primary, next_participants = _transition(
            primary,
            participants,
            action,
            actor.subject_id,
            target,
        )
        _same_actor(provider, actor, case, provider_id)
        if target in candidates:
            current = _candidates(case, actor, provider).get(target)
            if current is None or current.auth_epoch != candidates[target].auth_epoch:
                raise cases.CaseConflict("assignment_target_changed")
        event = AssignmentEvent(
            case=case,
            sequence=len(events) + 1,
            action=action,
            target_subject=target,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
            previous_sha256=events[-1].sha256 if events else ZERO_HASH,
        )
        event.sha256 = _digest(event)
        event.save(force_insert=True)
        event.refresh_from_db(fields=["transaction_id", "created_at"])
        _same_actor(provider, actor, case, provider_id)
        if target in candidates:
            current = _candidates(case, actor, provider).get(target)
            if current is None or current.auth_epoch != candidates[target].auth_epoch:
                raise cases.CaseConflict("assignment_target_changed")
        return _projection([*events, event], next_primary, next_participants, actor, {})
