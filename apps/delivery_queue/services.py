"""Atomic PostgreSQL delivery queue. Synthetic scope only; no network sender."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
import json
import re
import secrets

from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import ApprovalClaim, DeliveryAuditEvent, DeliveryIntent, ProviderReceipt

_HEX = re.compile(r"^[a-f0-9]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class QueueConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WorkerLease:
    intent_key: str
    token: str
    owner: str
    expires_at: object


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    plan_fingerprint: str
    expected_parts: int
    delivered_parts: int
    failed_parts: int
    uncertain_parts: int
    staged_parts: int
    leased_parts: int
    complete: bool
    state: str


def _postgres_only():
    if connection.vendor != "postgresql":
        raise QueueConflict("postgresql_backend_required")


def _audit(intent, old_state, new_state, reference, payload):
    DeliveryAuditEvent.objects.create(
        intent=intent, old_state=old_state, new_state=new_state,
        event_reference=reference,
        event_payload_sha256=sha256(payload).hexdigest(),
    )


def commit_approved_plan(
    *, receipt_id: str, nonce: str, approval_fingerprint: str,
    plan_fingerprint: str, case_key: str, answer_revision: int,
    provider: str, expires_at, parts: tuple[tuple[int, str], ...],
    verify_approval,
):
    """Atomically consume one approved receipt and persist its complete manifest."""
    _postgres_only()
    if (
        not _REF.fullmatch(receipt_id) or type(nonce) is not str or len(nonce) < 32
        or not _HEX.fullmatch(approval_fingerprint) or not _HEX.fullmatch(plan_fingerprint)
        or not _REF.fullmatch(case_key) or type(answer_revision) is not int or answer_revision < 1
        or not _REF.fullmatch(provider) or not callable(verify_approval)
        or not isinstance(parts, tuple) or not 1 <= len(parts) <= 16
        or expires_at <= timezone.now()
    ):
        raise QueueConflict("invalid_approval_plan")
    try:
        verified_approval = verify_approval()
    except Exception as exc:
        raise QueueConflict("approval_verifier_unavailable") from exc
    if verified_approval is not True:
        raise QueueConflict("approval_not_verified")
    normalized = []
    for ordinal, (number, digest) in enumerate(parts, 1):
        if number != ordinal or not _HEX.fullmatch(digest):
            raise QueueConflict("invalid_part_manifest")
        normalized.append([number, digest])
    manifest_sha = sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()
    nonce_sha = sha256(nonce.encode()).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        # Transaction-scoped advisory lock serializes the absent-row race too.
        with connection.cursor() as cursor:
            for lock_key in sorted((receipt_id, nonce_sha)):
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 201))", [lock_key])
        if ApprovalClaim.objects.filter(nonce_digest=nonce_sha).exclude(receipt_id=receipt_id).exists():
            raise QueueConflict("approval_nonce_already_consumed")
        claim = ApprovalClaim.objects.select_for_update().filter(receipt_id=receipt_id).first()
        if claim:
            if (
                claim.approval_fingerprint != approval_fingerprint
                or claim.plan_fingerprint != plan_fingerprint
                or claim.nonce_digest != nonce_sha
                or claim.parts_manifest_sha256 != manifest_sha
                or claim.case_key != case_key
                or claim.answer_revision != answer_revision
                or claim.expected_parts != len(parts)
            ):
                raise QueueConflict("approval_receipt_already_consumed_for_other_plan")
            intents = list(DeliveryIntent.objects.filter(approval=claim).order_by("ordinal"))
            if len(intents) != len(parts):
                raise QueueConflict("persisted_plan_manifest_incomplete")
            return tuple(intents)
        claim = ApprovalClaim.objects.create(
            receipt_id=receipt_id, nonce_digest=nonce_sha,
            approval_fingerprint=approval_fingerprint, plan_fingerprint=plan_fingerprint,
            case_key=case_key, answer_revision=answer_revision,
            expected_parts=len(parts), parts_manifest_sha256=manifest_sha,
            expires_at=expires_at, consumed_at=now,
        )
        intents = []
        for ordinal, digest in normalized:
            intent_key = sha256(f"{plan_fingerprint}:{ordinal}:{digest}".encode()).hexdigest()
            intent = DeliveryIntent.objects.create(
                intent_key=intent_key, approval=claim, plan_fingerprint=plan_fingerprint,
                case_key=case_key, provider=provider, answer_revision=answer_revision,
                ordinal=ordinal, payload_sha256=digest, state=DeliveryIntent.STAGED,
            )
            _audit(intent, "", DeliveryIntent.STAGED, "approval:" + receipt_id, digest.encode())
            intents.append(intent)
        return tuple(intents)


def claim_next(*, provider: str, worker_id: str, lease_seconds: int = 60) -> WorkerLease | None:
    """Claim one staged intent using SKIP LOCKED; no automatic expired-lease retry."""
    _postgres_only()
    if not _REF.fullmatch(provider) or not _REF.fullmatch(worker_id) or not 1 <= lease_seconds <= 300:
        raise QueueConflict("invalid_worker_claim")
    now = timezone.now()
    token = secrets.token_urlsafe(32)
    token_sha = sha256(token.encode()).hexdigest()
    expires = now + timedelta(seconds=lease_seconds)
    with transaction.atomic():
        intent = (
            DeliveryIntent.objects.select_for_update(skip_locked=True)
            .filter(provider=provider, state=DeliveryIntent.STAGED)
            .order_by("created_at", "intent_key").first()
        )
        if intent is None:
            return None
        intent.state = DeliveryIntent.LEASED
        intent.lease_token_sha256 = token_sha
        intent.lease_owner = worker_id
        intent.lease_expires_at = expires
        intent.save(update_fields=[
            "state", "lease_token_sha256", "lease_owner", "lease_expires_at", "updated_at"
        ])
        _audit(intent, DeliveryIntent.STAGED, DeliveryIntent.LEASED, "worker:" + worker_id, token_sha.encode())
        return WorkerLease(intent.intent_key, token, worker_id, expires)


def record_receipt(
    *, lease: WorkerLease, receipt_reference: str, provider_message_id: str,
    reported: str, verify_provider_receipt,
):
    """Persist provider proof and state transition atomically; exact replay only."""
    _postgres_only()
    if (
        not isinstance(lease, WorkerLease) or not _REF.fullmatch(receipt_reference)
        or not _REF.fullmatch(provider_message_id)
        or reported not in {"ACCEPTED", "DELIVERED", "FAILED"}
        or not callable(verify_provider_receipt)
    ):
        raise QueueConflict("invalid_provider_receipt")
    proof = {
        "intent_key": lease.intent_key, "receipt_reference": receipt_reference,
        "provider_message_id": provider_message_id, "reported": reported,
    }
    payload = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    payload_sha = sha256(payload).hexdigest()
    try:
        verified_receipt = verify_provider_receipt(proof)
    except Exception as exc:
        raise QueueConflict("provider_receipt_verifier_unavailable") from exc
    if verified_receipt is not True:
        raise QueueConflict("provider_receipt_unverified")
    target_state = {
        "ACCEPTED": DeliveryIntent.SENT_UNCONFIRMED,
        "DELIVERED": DeliveryIntent.DELIVERED,
        "FAILED": DeliveryIntent.FAILED_REQUIRES_REVIEW,
    }[reported]
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 202))", [receipt_reference])
        existing = ProviderReceipt.objects.select_for_update().filter(
            receipt_reference=receipt_reference
        ).first()
        if existing:
            if (
                existing.intent_id != lease.intent_key
                or existing.provider_message_id != provider_message_id
                or existing.reported != reported
                or existing.payload_sha256 != payload_sha
            ):
                raise QueueConflict("provider_receipt_reference_reused")
            return DeliveryIntent.objects.get(pk=lease.intent_key)
        intent = DeliveryIntent.objects.select_for_update().get(pk=lease.intent_key)
        if (
            intent.state not in {DeliveryIntent.LEASED, DeliveryIntent.UNKNOWN_REQUIRES_RECONCILIATION}
            or intent.lease_owner != lease.owner
            or intent.lease_token_sha256 != sha256(lease.token.encode()).hexdigest()
            or intent.lease_expires_at is None
        ):
            raise QueueConflict("worker_lease_mismatch")
        old = intent.state
        intent.state = target_state
        intent.provider_message_id = provider_message_id
        intent.provider_status = reported
        intent.lease_token_sha256 = None
        intent.lease_owner = None
        intent.lease_expires_at = None
        intent.save(update_fields=[
            "state", "provider_message_id", "provider_status",
            "lease_token_sha256", "lease_owner", "lease_expires_at", "updated_at",
        ])
        ProviderReceipt.objects.create(
            receipt_reference=receipt_reference, intent=intent,
            provider_message_id=provider_message_id, reported=reported,
            payload_sha256=payload_sha,
        )
        _audit(intent, old, target_state, receipt_reference, payload)
        return intent


def quarantine_expired_leases(*, now=None, limit: int = 100) -> tuple[str, ...]:
    """Move expired leases to reconciliation; never return them to STAGED."""
    _postgres_only()
    if not 1 <= limit <= 500:
        raise QueueConflict("invalid_reconciliation_limit")
    now = now or timezone.now()
    changed = []
    with transaction.atomic():
        rows = list(
            DeliveryIntent.objects.select_for_update(skip_locked=True)
            .filter(state=DeliveryIntent.LEASED, lease_expires_at__lte=now)
            .order_by("lease_expires_at", "intent_key")[:limit]
        )
        for intent in rows:
            old = intent.state
            intent.state = DeliveryIntent.UNKNOWN_REQUIRES_RECONCILIATION
            # Preserve the expired lease fingerprint so a late, independently
            # verified provider receipt can reconcile this exact attempt.
            intent.save(update_fields=["state", "updated_at"])
            _audit(intent, old, intent.state, "lease-expired:" + intent.intent_key, b"expired")
            changed.append(intent.intent_key)
    return tuple(changed)


def summarize_plan(plan_fingerprint: str) -> DeliverySummary:
    _postgres_only()
    if not _HEX.fullmatch(plan_fingerprint):
        raise QueueConflict("invalid_plan_fingerprint")
    intents = DeliveryIntent.objects.filter(plan_fingerprint=plan_fingerprint)
    claim = ApprovalClaim.objects.filter(plan_fingerprint=plan_fingerprint).first()
    if claim is None:
        raise QueueConflict("plan_not_found")
    counts = intents.aggregate(
        delivered=Count("pk", filter=Q(state=DeliveryIntent.DELIVERED)),
        failed=Count("pk", filter=Q(state=DeliveryIntent.FAILED_REQUIRES_REVIEW)),
        uncertain=Count("pk", filter=Q(state=DeliveryIntent.UNKNOWN_REQUIRES_RECONCILIATION)),
        staged=Count("pk", filter=Q(state=DeliveryIntent.STAGED)),
        leased=Count("pk", filter=Q(state=DeliveryIntent.LEASED)),
    )
    complete = counts["delivered"] == claim.expected_parts
    if complete:
        state = "DELIVERED"
    elif counts["uncertain"]:
        state = "NEEDS_RECONCILIATION"
    elif counts["failed"] and counts["delivered"]:
        state = "PARTIALLY_FAILED"
    elif counts["failed"]:
        state = "FAILED_REQUIRES_REVIEW"
    elif counts["delivered"]:
        state = "PARTIALLY_DELIVERED"
    elif counts["leased"]:
        state = "IN_PROGRESS"
    else:
        state = "STAGED"
    return DeliverySummary(
        plan_fingerprint, claim.expected_parts, counts["delivered"], counts["failed"],
        counts["uncertain"], counts["staged"], counts["leased"], complete, state,
    )
