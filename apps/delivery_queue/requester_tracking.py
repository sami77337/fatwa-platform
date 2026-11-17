"""Scoped requester tracking for multiple synthetic cases, without private content."""
from __future__ import annotations

import re
import secrets
from datetime import timedelta
from hashlib import sha256

from django.db import connection, transaction
from django.utils import timezone

from . import services as queue
from .models import (
    ApprovalClaim,
    DeliveryIntent,
    RequesterTrackingCase,
    RequesterTrackingEvent,
    RequesterTrackingToken,
)

_TOKEN = re.compile(r"^rt_[A-Za-z0-9_-]{43}$")
_STAGES = frozenset({
    "RECEIVED", "UNDER_REVIEW", "NEEDS_CLARIFICATION",
    "WITH_MUFTI", "RETURNED_FOR_CHANGES",
})
_TRANSITIONS = {
    "RECEIVED": frozenset({"UNDER_REVIEW", "NEEDS_CLARIFICATION"}),
    "UNDER_REVIEW": frozenset({"NEEDS_CLARIFICATION", "WITH_MUFTI"}),
    "NEEDS_CLARIFICATION": frozenset({"UNDER_REVIEW"}),
    "WITH_MUFTI": frozenset({"RETURNED_FOR_CHANGES", "UNDER_REVIEW"}),
    "RETURNED_FOR_CHANGES": frozenset({"UNDER_REVIEW"}),
}
_TICKET_MAX_LIFETIME = timedelta(days=30)
_GENERIC_TOKEN_DENIAL = "tracking_token_invalid_or_expired"
MAX_TRACKING_HISTORY = 128


class TrackingDenied(ValueError):
    """Fixed safe failure codes. Never echo a token or case identifier."""


def _guard_database():
    try:
        queue._postgres_only()
    except queue.QueueConflict as exc:
        raise TrackingDenied("tracking_backend_unavailable") from exc


def _operator_allowed(actor_id, case_key, verifier, *, stage=None):
    if not queue._ref(actor_id) or not queue._ref(case_key) or not callable(verifier):
        raise TrackingDenied("tracking_authorization_required")
    try:
        result = verifier(actor_id, case_key) if stage is None else verifier(actor_id, case_key, stage)
    except Exception as exc:
        raise TrackingDenied("tracking_authorization_unavailable") from exc
    if result is not True:
        raise TrackingDenied("tracking_authorization_denied")


def _expiry_valid(value):
    return (
        queue._utc(value)
        and timezone.now() < value <= timezone.now() + _TICKET_MAX_LIFETIME
    )


def _verify_case_history(case):
    """Fail closed if the current lifecycle lacks an exact append-only chain."""
    events = list(
        RequesterTrackingEvent.objects.filter(case=case)
        .order_by("sequence")[:MAX_TRACKING_HISTORY + 1]
    )
    if (
        not 1 <= case.revision <= MAX_TRACKING_HISTORY
        or len(events) != case.revision
    ):
        raise TrackingDenied("tracking_history_inconsistent")
    current = ""
    for number, event in enumerate(events, 1):
        if (
            event.sequence != number
            or event.old_stage != current
            or not queue._ref(event.actor_id)
            or (
                (number == 1 and event.new_stage != "RECEIVED")
                or (number > 1 and event.new_stage not in _TRANSITIONS.get(current, frozenset()))
            )
        ):
            raise TrackingDenied("tracking_history_inconsistent")
        current = event.new_stage
    if current != case.stage:
        raise TrackingDenied("tracking_history_inconsistent")


def _lock_case_key(case_key):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,208))",
            ["requester-case:" + case_key],
        )


def _require_standalone_tracking(case_key):
    """A bound durable case must never use this legacy independent projection.

    Check the database as well as the reserved namespace: the old review settings
    may access a database migrated by casework without installing its Django app.
    Do not import the canonical model or acquire its lock from this legacy path.
    """
    if case_key.startswith("case:"):
        raise TrackingDenied("canonical_case_service_required")
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('casework_case')")
        if cursor.fetchone()[0] is None:
            return
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM casework_case WHERE tracking_id = %s)",
            [case_key],
        )
        if cursor.fetchone()[0]:
            raise TrackingDenied("canonical_case_service_required")


def _issue(case, expires_at):
    token = "rt_" + secrets.token_urlsafe(32)
    digest = sha256(token.encode("ascii")).hexdigest()
    RequesterTrackingToken.objects.create(
        token_sha256=digest, case=case, expires_at=expires_at,
    )
    return token


def provision_tracking_case(*, case_key, operator_id, authorize_operator, expires_at):
    """Authorized local provisioning. Token is returned exactly once, never sent."""
    if not queue._ref(case_key) or not _expiry_valid(expires_at):
        raise TrackingDenied("tracking_case_or_expiry_invalid")
    _guard_database()
    with transaction.atomic():
        _lock_case_key(case_key)
        _require_standalone_tracking(case_key)
        _operator_allowed(operator_id, case_key, authorize_operator)
        if RequesterTrackingCase.objects.filter(pk=case_key).exists():
            raise TrackingDenied("tracking_case_already_registered")
        case = RequesterTrackingCase.objects.create(
            case_key=case_key, stage="RECEIVED", revision=1,
            registered_by=operator_id,
        )
        RequesterTrackingEvent.objects.create(
            case=case, sequence=1, old_stage="", new_stage="RECEIVED",
            actor_id=operator_id,
        )
        return _issue(case, expires_at)


def rotate_tracking_token(*, case_key, operator_id, authorize_operator, expires_at):
    """Revoke old tracking access and generate one new random capability."""
    if not queue._ref(case_key) or not _expiry_valid(expires_at):
        raise TrackingDenied("tracking_case_or_expiry_invalid")
    _guard_database()
    with transaction.atomic():
        _lock_case_key(case_key)
        _require_standalone_tracking(case_key)
        _operator_allowed(operator_id, case_key, authorize_operator)
        case = RequesterTrackingCase.objects.select_for_update().filter(pk=case_key).first()
        if case is None:
            raise TrackingDenied("tracking_case_not_found")
        _verify_case_history(case)
        RequesterTrackingToken.objects.filter(
            case=case, revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())
        return _issue(case, expires_at)


def advance_tracking_case(*, case_key, expected_revision, stage, actor_id, authorize_actor):
    """Versioned operational notes only; cannot claim approval/publication."""
    if (
        not queue._ref(case_key)
        or type(expected_revision) is not int or expected_revision < 1
        or type(stage) is not str or stage not in _STAGES
    ):
        raise TrackingDenied("tracking_transition_invalid")
    _guard_database()
    with transaction.atomic():
        _lock_case_key(case_key)
        _require_standalone_tracking(case_key)
        _operator_allowed(actor_id, case_key, authorize_actor, stage=stage)
        case = RequesterTrackingCase.objects.select_for_update().filter(pk=case_key).first()
        if case is None:
            raise TrackingDenied("tracking_case_not_found")
        _verify_case_history(case)
        if case.revision != expected_revision:
            raise TrackingDenied("tracking_revision_changed")
        if stage not in _TRANSITIONS.get(case.stage, frozenset()):
            raise TrackingDenied("tracking_transition_forbidden")
        old = case.stage
        case.stage = stage
        case.revision += 1
        case.save(update_fields=["stage", "revision", "updated_at"])
        RequesterTrackingEvent.objects.create(
            case=case, sequence=case.revision,
            old_stage=old, new_stage=stage, actor_id=actor_id,
        )
        return {"status":stage, "revision":case.revision}


def lookup_case_status(token):
    """Private coarse status for exactly one case; never reveals case keys.

    A locally stored DELIVERED label is not accepted as cryptographically
    verified provider evidence. Confirmation of human reading is never inferred.
    """
    if type(token) is not str or _TOKEN.fullmatch(token) is None:
        raise TrackingDenied(_GENERIC_TOKEN_DENIAL)
    _guard_database()
    token_hash = sha256(token.encode("ascii")).hexdigest()
    with transaction.atomic():
        grant = RequesterTrackingToken.objects.select_related(
            "case",
        ).filter(token_sha256=token_hash).first()
        if (
            grant is None or grant.revoked_at is not None
            or grant.expires_at <= timezone.now()
        ):
            raise TrackingDenied(_GENERIC_TOKEN_DENIAL)
        _require_standalone_tracking(grant.case_id)
        case = RequesterTrackingCase.objects.select_for_update().get(
            pk=grant.case_id,
        )
        _require_standalone_tracking(case.case_key)
        # Rotation uses this row lock. Re-read after waiting so a token revoked
        # by the lock holder cannot authorize a stale status response.
        grant = RequesterTrackingToken.objects.filter(token_sha256=token_hash).first()
        if (
            grant is None or grant.case_id != case.pk or grant.revoked_at is not None
            or grant.expires_at <= timezone.now()
        ):
            raise TrackingDenied(_GENERIC_TOKEN_DENIAL)
        _verify_case_history(case)
        # Verify against the same locked audit-head snapshot as operator reports.
        queue._verify_locked_head(queue._locked_head())
        candidates = list(
            ApprovalClaim.objects.filter(case_key=case.case_key)
            .order_by("-answer_revision", "-consumed_at", "receipt_id")[:2]
        )
        if not candidates:
            return {
                "schema":"fatwa.requester-tracking.v1",
                "status":case.stage,
                "total_parts":0,
                "delivered_parts":0,
                "delivery_verified":False,
            }
        if (
            len(candidates) > 1
            and candidates[0].answer_revision == candidates[1].answer_revision
        ):
            return {
                "schema":"fatwa.requester-tracking.v1",
                "status":"DELIVERY_NEEDS_RECONCILIATION",
                "total_parts":0,
                "delivered_parts":0,
                "delivery_verified":False,
            }
        claim = candidates[0]
        rows = list(DeliveryIntent.objects.filter(
            approval=claim,
        ).order_by("ordinal"))
        summary = queue._summary_from_rows(claim, rows)
        mapping = {
            "STAGED":"PREPARING_DELIVERY",
            "IN_PROGRESS":"DELIVERY_IN_PROGRESS",
            "PARTIALLY_DELIVERED":"PARTIALLY_REPORTED",
            "DELIVERED":"PROVIDER_REPORTED_DELIVERY_UNVERIFIED",
            "NEEDS_RECONCILIATION":"DELIVERY_NEEDS_RECONCILIATION",
            "FAILED_REQUIRES_REVIEW":"DELIVERY_REQUIRES_REVIEW",
            "PARTIALLY_FAILED":"DELIVERY_REQUIRES_REVIEW",
        }
        if case.stage in {"NEEDS_CLARIFICATION", "RETURNED_FOR_CHANGES"}:
            status = "DELIVERY_NEEDS_RECONCILIATION"
        else:
            status = mapping.get(summary.state, "DELIVERY_NEEDS_RECONCILIATION")
        return {
            "schema":"fatwa.requester-tracking.v1",
            "status":status,
            "total_parts":summary.expected_parts,
            "delivered_parts":summary.delivered_parts,
            "delivery_verified":False,
        }
