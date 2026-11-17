"""Owned synthetic PostgreSQL queue. No sender or production activation."""
from __future__ import annotations

import json
import re
import secrets
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from types import MappingProxyType

from django.db import connection, transaction
from django.utils import timezone

from apps.intake_workflow.guards import (
    SyntheticWriteDenied,
    require_synthetic_write,
    validate_write_configuration,
)

from .models import (
    ApprovalClaim,
    DeliveryAttempt,
    DeliveryAuditEvent,
    DeliveryAuditHead,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
    SignedDeliveryContext,
)

_QUEUE_UNIT = ContextVar("fatwa_owned_queue_unit", default=None)
_HEX = re.compile(r"[a-f0-9]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{32,128}")
MAX_AUDIT_EVENTS = 10000
_TRANSITIONS = {
    "": {"STAGED"},
    "STAGED": {"LEASED"},
    "LEASED": {"SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW", "UNKNOWN_REQUIRES_RECONCILIATION"},
    "UNKNOWN_REQUIRES_RECONCILIATION": {"SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"},
    "SENT_UNCONFIRMED": {"DELIVERED", "FAILED_REQUIRES_REVIEW"},
}


class QueueConflict(ValueError):
    """Fixed error codes; never disclose credentials or answer content."""


@dataclass(frozen=True, slots=True)
class WorkerLease:
    intent_key: str
    token: str
    owner: str
    expires_at: datetime


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
    accepted_parts: int = 0


def _ref(value, limit=128):
    return type(value) is str and len(value) <= limit and _REF.fullmatch(value) is not None


def _hex(value):
    return type(value) is str and _HEX.fullmatch(value) is not None


def _utc(value):
    return isinstance(value, datetime) and timezone.is_aware(value) and value.utcoffset() == timedelta(0)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _event_ref(prefix, value):
    candidate = prefix + ":" + value
    return candidate if len(candidate) <= 128 else prefix + ":" + sha256(value.encode()).hexdigest()


def _postgres_only():
    # The existing guard checks explicit development flags before opening SQL,
    # then verifies the actual DB identity, ownership and synthetic schema.
    if connection.vendor != "postgresql":
        raise QueueConflict("postgresql_backend_required")
    try:
        unit = _QUEUE_UNIT.get()
        if unit is None:
            return require_synthetic_write(synthetic_fixtures_only=True)
        raw_connection, block, owned = unit
        target = validate_write_configuration(synthetic_fixtures_only=True)
        if (connection.connection is not raw_connection or not connection.in_atomic_block
            or block not in connection.atomic_blocks
            or target.database_name != owned.database_name):
            raise QueueConflict("owned_queue_transaction_changed")
        return owned
    except SyntheticWriteDenied as exc:
        raise QueueConflict("synthetic_database_not_authorized") from exc


@contextmanager
def synthetic_queue_atomic():
    """Compose case + queue writes after the sole ownership guard, never bypass it.

    Only this context can reuse its guard in nested queue calls. The binding is
    execution-local and pinned to the actual connection and live atomic block;
    arbitrary caller transactions still fail the original preflight guard.
    """
    owned = _postgres_only()
    with transaction.atomic():
        block = connection.atomic_blocks[-1]
        token = _QUEUE_UNIT.set((connection.connection, block, owned))
        try:
            yield
        finally:
            _QUEUE_UNIT.reset(token)


def _audit_payload(sequence, intent_id, old_state, new_state, reference, payload_sha, recorded_at):
    return [sequence, intent_id, old_state, new_state, reference, payload_sha,
            recorded_at.isoformat(timespec="microseconds")]


def _locked_head(*, create=False):
    head = DeliveryAuditHead.objects.select_for_update().filter(pk=1).first()
    if head is not None:
        return head
    if DeliveryAuditEvent.objects.exists() or DeliveryIntent.objects.exists():
        raise QueueConflict("delivery_audit_head_missing")
    if not create:
        return None
    # The unique singleton key also serializes the initially absent-row race.
    DeliveryAuditHead.objects.get_or_create(pk=1, defaults={"sequence": 0, "digest": ""})
    return DeliveryAuditHead.objects.select_for_update().get(pk=1)


def _verify_locked_head(head, *, check_states=True):
    if head is None:
        return 0, ""
    if DeliveryAuditHead.objects.exclude(pk=1).exists():
        raise QueueConflict("delivery_audit_head_invalid")
    events = list(DeliveryAuditEvent.objects.order_by("sequence")[:MAX_AUDIT_EVENTS + 1])
    if len(events) > MAX_AUDIT_EVENTS:
        raise QueueConflict("delivery_audit_capacity")
    previous, latest = "", {}
    for count, event in enumerate(events, 1):
        payload = _audit_payload(event.sequence, event.intent_id, event.old_state,
            event.new_state, event.event_reference, event.event_payload_sha256, event.recorded_at)
        expected = sha256((previous + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))).encode()).hexdigest()
        if (event.sequence != count or event.previous_digest != previous
            or not compare_digest(event.digest, expected)
            or not _hex(event.event_payload_sha256) or not _ref(event.event_reference)
            or not _utc(event.recorded_at)
            or latest.get(event.intent_id, "") != event.old_state
            or event.new_state not in _TRANSITIONS.get(event.old_state, set())):
            raise QueueConflict("delivery_audit_chain_invalid")
        latest[event.intent_id] = event.new_state
        previous = expected
    if head.sequence != len(events) or not compare_digest(head.digest, previous):
        raise QueueConflict("delivery_audit_head_mismatch")
    if check_states:
        actual = dict(DeliveryIntent.objects.values_list("intent_key", "state"))
        if actual != latest:
            raise QueueConflict("delivery_audit_state_mismatch")
    return head.sequence, head.digest


def verify_audit_chain():
    _postgres_only()
    with transaction.atomic():
        return _verify_locked_head(_locked_head())


def _audit(intent, old_state, new_state, reference, payload):
    head = _locked_head()
    if head is None:
        raise QueueConflict("delivery_audit_head_missing")
    # Caller has changed the intent in this transaction; validate the prior
    # chain, then append its matching event under the same locked head.
    _verify_locked_head(head, check_states=False)
    if head.sequence >= MAX_AUDIT_EVENTS:
        raise QueueConflict("delivery_audit_capacity")
    recorded, sequence = timezone.now(), head.sequence + 1
    payload_sha = sha256(payload).hexdigest()
    event_payload = _audit_payload(sequence, intent.pk, old_state, new_state, reference, payload_sha, recorded)
    digest = sha256((head.digest + json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))).encode()).hexdigest()
    DeliveryAuditEvent.objects.create(intent=intent, sequence=sequence,
        old_state=old_state, new_state=new_state, event_reference=reference,
        event_payload_sha256=payload_sha, previous_digest=head.digest,
        digest=digest, recorded_at=recorded)
    head.sequence, head.digest = sequence, digest
    head.save(update_fields=["sequence", "digest"])


def _verify(callback, value=None, *, no_argument=False, error="verification_failed"):
    try:
        result = callback() if no_argument else callback(value)
    except Exception as exc:
        raise QueueConflict(error + "_unavailable") from exc
    if result is not True:
        raise QueueConflict(error)


def _validate_manifest(claim, rows):
    manifest = [[row.ordinal, row.payload_sha256] for row in rows]
    digest = sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()
    if (len(rows) != claim.expected_parts
        or [r.ordinal for r in rows] != list(range(1, claim.expected_parts + 1))
        or not compare_digest(digest, claim.parts_manifest_sha256)
        or any(r.approval_id != claim.pk or r.case_key != claim.case_key
               or r.answer_revision != claim.answer_revision
               or r.plan_fingerprint != claim.plan_fingerprint for r in rows)
        or len({r.provider for r in rows}) != 1):
        raise QueueConflict("plan_manifest_integrity_mismatch")


def commit_approved_plan(*, receipt_id, nonce, approval_fingerprint, plan_fingerprint,
                         case_key, answer_revision, provider, expires_at, parts,
                         verify_approval, signed_context=None):
    """Internal synthetic API. Network-facing callers must use the signed adapter."""
    _postgres_only()
    if (not _ref(receipt_id) or type(nonce) is not str or _NONCE.fullmatch(nonce) is None
        or not _hex(approval_fingerprint) or not _hex(plan_fingerprint)
        or not _ref(case_key) or type(answer_revision) is not int or answer_revision < 1
        or not _ref(provider, 64) or not callable(verify_approval)
        or type(parts) is not tuple or not 1 <= len(parts) <= 16
        or not _utc(expires_at) or expires_at <= timezone.now()):
        raise QueueConflict("invalid_approval_plan")
    normalized = []
    for ordinal, item in enumerate(parts, 1):
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not int
            or item[0] != ordinal or not _hex(item[1])):
            raise QueueConflict("invalid_part_manifest")
        normalized.append([item[0], item[1]])
    context_bytes = None
    if signed_context is not None:
        if type(signed_context) is not dict or set(signed_context) != {"schema", "receipt", "evidence", "plan"}:
            raise QueueConflict("invalid_signed_context")
        try:
            context_bytes = _canonical(signed_context)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise QueueConflict("invalid_signed_context") from exc
        if len(context_bytes) > 32768:
            raise QueueConflict("signed_context_too_large")
    manifest_sha = sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()
    nonce_sha = sha256(nonce.encode()).hexdigest()
    with transaction.atomic():
        with connection.cursor() as cursor:
            for key in sorted(("receipt:" + receipt_id, "nonce:" + nonce_sha, "plan:" + plan_fingerprint)):
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 201))", [key])
        if expires_at <= timezone.now():
            raise QueueConflict("approval_expired_after_lock")
        _verify(verify_approval, no_argument=True, error="approval_not_verified")
        if expires_at <= timezone.now():
            raise QueueConflict("approval_expired_during_verification")
        if ApprovalClaim.objects.filter(nonce_digest=nonce_sha).exclude(receipt_id=receipt_id).exists():
            raise QueueConflict("approval_nonce_already_consumed")
        claim = ApprovalClaim.objects.select_for_update().filter(pk=receipt_id).first()
        if claim is not None:
            if (claim.approval_fingerprint != approval_fingerprint
                or claim.plan_fingerprint != plan_fingerprint or claim.nonce_digest != nonce_sha
                or claim.parts_manifest_sha256 != manifest_sha or claim.case_key != case_key
                or claim.answer_revision != answer_revision or claim.expected_parts != len(parts)):
                raise QueueConflict("approval_receipt_already_consumed_for_other_plan")
            saved_context = SignedDeliveryContext.objects.filter(approval=claim).first()
            if (saved_context is None) != (signed_context is None):
                raise QueueConflict("signed_context_mismatch")
            if saved_context and (saved_context.envelope != signed_context
                or saved_context.envelope_sha256 != sha256(context_bytes).hexdigest()):
                raise QueueConflict("signed_context_mismatch")
            rows = list(DeliveryIntent.objects.filter(approval=claim).order_by("ordinal"))
            _validate_manifest(claim, rows)
            if any(row.provider != provider for row in rows):
                raise QueueConflict("persisted_provider_mismatch")
            _verify_locked_head(_locked_head())
            return tuple(rows)
        if ApprovalClaim.objects.filter(plan_fingerprint=plan_fingerprint).exists():
            raise QueueConflict("plan_already_has_approval")
        _verify_locked_head(_locked_head(create=True))
        claim = ApprovalClaim.objects.create(receipt_id=receipt_id, nonce_digest=nonce_sha,
            approval_fingerprint=approval_fingerprint, plan_fingerprint=plan_fingerprint,
            case_key=case_key, answer_revision=answer_revision, expected_parts=len(parts),
            parts_manifest_sha256=manifest_sha, expires_at=expires_at, consumed_at=timezone.now())
        if signed_context is not None:
            SignedDeliveryContext.objects.create(approval=claim, envelope=signed_context,
                envelope_sha256=sha256(context_bytes).hexdigest())
        rows = []
        for ordinal, digest in normalized:
            intent_key = sha256(f"{plan_fingerprint}:{ordinal}:{digest}".encode()).hexdigest()
            intent = DeliveryIntent.objects.create(intent_key=intent_key, approval=claim,
                plan_fingerprint=plan_fingerprint, case_key=case_key, provider=provider,
                answer_revision=answer_revision, ordinal=ordinal, payload_sha256=digest, state="STAGED")
            _audit(intent, "", "STAGED", _event_ref("approval", receipt_id), digest.encode())
            rows.append(intent)
        return tuple(rows)


def claim_next(*, provider, worker_id, lease_seconds=60, plan_fingerprint=None, verify_claim=None):
    """Claim a single row; signed plans additionally require post-lock verification."""
    _postgres_only()
    if (not _ref(provider, 64) or not _ref(worker_id) or type(lease_seconds) is not int
        or not 1 <= lease_seconds <= 300 or (plan_fingerprint is not None and not _hex(plan_fingerprint))
        or (verify_claim is not None and not callable(verify_claim))):
        raise QueueConflict("invalid_worker_claim")
    with transaction.atomic():
        query = DeliveryIntent.objects.select_for_update(skip_locked=True, of=("self",)).select_related("approval").filter(
            provider=provider, state="STAGED", approval__expires_at__gt=timezone.now())
        if plan_fingerprint is not None:
            query = query.filter(plan_fingerprint=plan_fingerprint)
        intent = query.order_by("created_at", "ordinal", "intent_key").first()
        if intent is None:
            return None
        has_context = SignedDeliveryContext.objects.filter(approval=intent.approval).exists()
        if has_context and verify_claim is None:
            raise QueueConflict("signed_claim_requires_current_verification")
        if verify_claim is not None:
            _verify(verify_claim, intent.approval, error="current_claim_not_verified")
        if intent.approval.expires_at <= timezone.now():
            raise QueueConflict("approval_expired_before_lease")
        token = secrets.token_urlsafe(32)
        token_sha = sha256(token.encode()).hexdigest()
        expires = min(timezone.now() + timedelta(seconds=lease_seconds), intent.approval.expires_at)
        DeliveryAttempt.objects.create(intent=intent, worker_id=worker_id, token_sha256=token_sha, expires_at=expires)
        intent.state, intent.lease_token_sha256 = "LEASED", token_sha
        intent.lease_owner, intent.lease_expires_at = worker_id, expires
        intent.save(update_fields=["state", "lease_token_sha256", "lease_owner", "lease_expires_at", "updated_at"])
        _audit(intent, "STAGED", "LEASED", _event_ref("worker", worker_id), token_sha.encode())
        return WorkerLease(intent.pk, token, worker_id, expires)


def _authenticate_attempt(intent, lease):
    attempt = DeliveryAttempt.objects.filter(intent=intent).first()
    token_sha = sha256(lease.token.encode()).hexdigest()
    if (attempt is None or attempt.worker_id != lease.owner
        or not compare_digest(attempt.token_sha256, token_sha)
        or attempt.expires_at != lease.expires_at):
        raise QueueConflict("worker_lease_mismatch")


def record_receipt(*, lease, receipt_reference, provider_message_id, reported, verify_provider_receipt,
                   signed_evidence=None):
    """Exact signed-event replay is idempotent, but still authenticates its attempt."""
    _postgres_only()
    if (not isinstance(lease, WorkerLease) or not _hex(lease.intent_key)
        or type(lease.token) is not str or not 32 <= len(lease.token) <= 128
        or not _ref(lease.owner) or not _utc(lease.expires_at)
        or not _ref(receipt_reference) or not _ref(provider_message_id)
        or type(reported) is not str or reported not in {"ACCEPTED", "DELIVERED", "FAILED"}
        or not callable(verify_provider_receipt)):
        raise QueueConflict("invalid_provider_receipt")
    # This optional evidence is reserved for the offline signed-provider adapter.
    # The low-level bool callback remains a synthetic-fixture interface only.
    evidence_sha = None
    if signed_evidence is not None:
        if (type(signed_evidence) is not dict
            or "signature_b64url" not in signed_evidence
            or type(signed_evidence["signature_b64url"]) is not str):
            raise QueueConflict("signed_provider_evidence_invalid")
        try:
            serialized = _canonical(signed_evidence)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise QueueConflict("signed_provider_evidence_invalid") from exc
        if len(serialized) > 4096:
            raise QueueConflict("signed_provider_evidence_too_large")
        evidence_sha = sha256(serialized).hexdigest()
    proof = {"intent_key": lease.intent_key, "receipt_reference": receipt_reference,
             "provider_message_id": provider_message_id, "reported": reported}
    # Retain the original ASCII-escaped canonical representation for existing proofs.
    payload = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    _verify(verify_provider_receipt, MappingProxyType(proof), error="provider_receipt_unverified")
    payload_sha = sha256(payload).hexdigest()
    target = {"ACCEPTED": "SENT_UNCONFIRMED", "DELIVERED": "DELIVERED", "FAILED": "FAILED_REQUIRES_REVIEW"}[reported]
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 202))", [receipt_reference])
        intent = DeliveryIntent.objects.select_for_update().filter(pk=lease.intent_key).first()
        if intent is None:
            raise QueueConflict("delivery_intent_not_found")
        _authenticate_attempt(intent, lease)
        existing = ProviderReceipt.objects.filter(pk=receipt_reference).first()
        if existing:
            if (existing.intent_id != lease.intent_key or existing.provider_message_id != provider_message_id
                or existing.reported != reported or not compare_digest(existing.payload_sha256, payload_sha)):
                raise QueueConflict("provider_receipt_reference_reused")
            if signed_evidence is not None:
                saved = ProviderSignatureEvidence.objects.filter(
                    receipt_id=receipt_reference
                ).first()
                if (saved is None or saved.envelope != signed_evidence
                    or not compare_digest(saved.envelope_sha256, evidence_sha)):
                    raise QueueConflict("signed_provider_evidence_replay_mismatch")
            _verify_locked_head(_locked_head())
            return intent
        if target not in _TRANSITIONS.get(intent.state, set()):
            raise QueueConflict("provider_receipt_state_not_advancing")
        if intent.provider_message_id is not None and intent.provider_message_id != provider_message_id:
            raise QueueConflict("provider_message_identity_mismatch")
        old = intent.state
        intent.state, intent.provider_message_id, intent.provider_status = target, provider_message_id, reported
        intent.lease_token_sha256 = intent.lease_owner = intent.lease_expires_at = None
        intent.save(update_fields=["state", "provider_message_id", "provider_status", "lease_token_sha256",
                                   "lease_owner", "lease_expires_at", "updated_at"])
        saved_receipt = ProviderReceipt.objects.create(
            receipt_reference=receipt_reference, intent=intent,
            provider_message_id=provider_message_id, reported=reported,
            payload_sha256=payload_sha,
        )
        if signed_evidence is not None:
            ProviderSignatureEvidence.objects.create(
                receipt=saved_receipt, envelope=signed_evidence,
                envelope_sha256=evidence_sha,
            )
        _audit(intent, old, target, receipt_reference, payload)
        return intent


def quarantine_expired_leases(*, now=None, limit=100, plan_fingerprint=None):
    """Quarantine uncertainty without retry; optionally restrict to one exact plan."""
    _postgres_only()
    if (type(limit) is not int or not 1 <= limit <= 500
        or (now is not None and not _utc(now))
        or (plan_fingerprint is not None and not _hex(plan_fingerprint))):
        raise QueueConflict("invalid_reconciliation_limit_or_clock")
    current, changed = now or timezone.now(), []
    with transaction.atomic():
        query = DeliveryIntent.objects.select_for_update(skip_locked=True).filter(
            state="LEASED", lease_expires_at__lte=current)
        if plan_fingerprint is not None:
            query = query.filter(plan_fingerprint=plan_fingerprint)
        rows = list(query.order_by("lease_expires_at", "intent_key")[:limit])
        for intent in rows:
            intent.state = "UNKNOWN_REQUIRES_RECONCILIATION"
            intent.save(update_fields=["state", "updated_at"])
            _audit(intent, "LEASED", intent.state, "lease-expired:" + intent.pk, b"expired")
            changed.append(intent.pk)
    return tuple(changed)


def _summary_from_rows(claim, rows):
    _validate_manifest(claim, rows)
    counts = Counter(row.state for row in rows)
    delivered, failed = counts["DELIVERED"], counts["FAILED_REQUIRES_REVIEW"]
    uncertain, accepted = counts["UNKNOWN_REQUIRES_RECONCILIATION"], counts["SENT_UNCONFIRMED"]
    complete = delivered == claim.expected_parts
    if complete:
        state = "DELIVERED"
    elif uncertain:
        state = "NEEDS_RECONCILIATION"
    elif failed:
        state = "PARTIALLY_FAILED" if delivered else "FAILED_REQUIRES_REVIEW"
    elif delivered:
        state = "PARTIALLY_DELIVERED"
    elif counts["LEASED"] or accepted:
        state = "IN_PROGRESS"
    else:
        state = "STAGED"
    return DeliverySummary(claim.plan_fingerprint, claim.expected_parts, delivered, failed,
        uncertain, counts["STAGED"], counts["LEASED"], complete, state, accepted)


def summarize_plan(plan_fingerprint):
    _postgres_only()
    if not _hex(plan_fingerprint):
        raise QueueConflict("invalid_plan_fingerprint")
    with transaction.atomic():
        # Holding the audit head prevents a writer from committing between the
        # manifest read and status calculation; readers never lock intent rows.
        _verify_locked_head(_locked_head())
        claim = ApprovalClaim.objects.filter(plan_fingerprint=plan_fingerprint).first()
        if claim is None:
            raise QueueConflict("plan_not_found")
        rows = list(DeliveryIntent.objects.filter(approval=claim).order_by("ordinal"))
        return _summary_from_rows(claim, rows)
