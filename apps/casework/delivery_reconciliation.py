"""Scoped delivery follow-up: inspect evidence and quarantine expired attempts.

No automatic retry, new lease, signature, publication or external request.
The bound case/approval/plan and signed evidence remain owned by delivery.py.
"""

from hmac import compare_digest

from django.utils import timezone

from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent, ProviderSignatureEvidence
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    audit_provider_reported_delivery,
    verify_stored_provider_evidence,
)

from . import delivery
from .services import CaseConflict

SCHEMA = "fatwa.case-delivery-followup.v1"


def _report(case, binding, verifier):
    # Case lock is held by the caller. A read-only snapshot locks the audit head,
    # never intent rows, so writers holding an intent can finish after this read.
    queue._verify_locked_head(queue._locked_head())
    rows = list(DeliveryIntent.objects.filter(approval=binding.approval).order_by("ordinal"))
    summary = queue._summary_from_rows(binding.approval, rows)
    trusted = isinstance(verifier, Ed25519ProviderEventVerifier)
    audit = (
        audit_provider_reported_delivery(
            plan_fingerprint=binding.approval.plan_fingerprint,
            verifier=verifier,
        )
        if trusted
        else None
    )
    now = timezone.now()
    parts = []
    for row in rows:
        expired = row.state == "LEASED" and row.lease_expires_at <= now
        proof = "NOT_REPORTED_DELIVERED"
        if row.state == "DELIVERED":
            proof = "UNVERIFIED" if trusted else "VERIFIER_UNAVAILABLE"
            if trusted:
                references = ProviderSignatureEvidence.objects.filter(
                    receipt__intent_id=row.pk,
                    receipt__reported="DELIVERED",
                ).values_list("receipt_id", flat=True)[:4]
                if any(
                    verify_stored_provider_evidence(receipt_reference=ref, verifier=verifier)
                    for ref in references
                ):
                    proof = "VERIFIED_PROVIDER_REPORT"
        if expired:
            action = "QUARANTINE_EXPIRED_ATTEMPT"
        elif row.state in ("UNKNOWN_REQUIRES_RECONCILIATION", "FAILED_REQUIRES_REVIEW"):
            action = "REVIEW_PROVIDER_OUTCOME_NO_RETRY"
        elif row.state == "DELIVERED":
            action = "NO_ACTION" if proof == "VERIFIED_PROVIDER_REPORT" else "CHECK_SIGNED_EVIDENCE"
        elif row.state == "STAGED":
            action = (
                "NEW_MUFTI_REVIEW_REQUIRED"
                if binding.approval.expires_at <= now
                else "TRUSTED_RESERVATION_REQUIRED"
            )
        else:
            action = "AWAIT_PROVIDER_OUTCOME"
        parts.append(
            {
                "ordinal": row.ordinal,
                "state": row.state,
                "lease_expired": expired,
                "provider_evidence": proof,
                "next_action": action,
            }
        )
    verified = bool(audit and audit.cryptographically_verified_complete) and all(
        part["provider_evidence"] == "VERIFIED_PROVIDER_REPORT" for part in parts
    )
    status = audit.status if audit else "EVIDENCE_UNAVAILABLE"
    if audit and audit.cryptographically_verified_complete and not verified:
        status = "PROVIDER_EVIDENCE_INCOMPLETE"
    return {
        "schema": SCHEMA,
        "public_ref": case.public_ref,
        "case_revision": case.revision,
        "evidence_version": case.evidence_version,
        "answer_revision": case.answer_revision,
        "plan_sha256": binding.approval.plan_fingerprint,
        "generated_at": now.isoformat(),
        "authorization_expired": binding.approval.expires_at <= now,
        "queue_state": summary.state,
        "delivery_status": status,
        "delivery_verified": verified,
        "read_confirmed": False,
        "automatic_retry_allowed": False,
        "expected_parts": summary.expected_parts,
        "quarantinable_parts": sum(part["lease_expired"] for part in parts),
        "parts": parts,
    }


def read_case_delivery_followup(
    *,
    case_id,
    subject_id,
    provider,
    verifier=None,
    synthetic_fixtures_only=False,
):
    """Read-only staff report of the current approved case's exact bound plan.

    Both provider and optional verifier must be trusted server configuration.
    Returned identifiers are scoped staff metadata; no text or bearer secrets.
    """
    with delivery._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, binding, _ = delivery._bound(case)
        delivery._approver(decision, identity, provider)
        result = _report(case, binding, verifier)
        delivery._evidence_reader(case, decision, provider, subject_id)(case.public_ref)
        return result


def quarantine_case_delivery(
    *,
    case_id,
    subject_id,
    provider,
    expected_plan_sha256,
    verifier=None,
    synthetic_fixtures_only=False,
):
    """Move only expired leases of the displayed current plan to uncertainty.

    Uses server time, checks current case/identity again, and retains the original
    immutable attempt for late signed receipts. It neither retries nor dispatches.
    """
    if not queue._hex(expected_plan_sha256):
        raise CaseConflict("invalid_expected_delivery_plan")
    with delivery._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, binding, _ = delivery._bound(case)
        delivery._approver(decision, identity, provider)
        if not compare_digest(expected_plan_sha256, binding.approval.plan_fingerprint):
            raise CaseConflict("case_delivery_plan_changed")
        # Do not take the audit head before the intent locks used by quarantine.
        changed = queue.quarantine_expired_leases(
            plan_fingerprint=binding.approval.plan_fingerprint,
            limit=16,
        )
        result = _report(case, binding, verifier)
        delivery._evidence_reader(case, decision, provider, subject_id)(case.public_ref)
        return {**result, "quarantined_parts": len(changed)}
