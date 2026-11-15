"""Bind Ed25519 MUFTI receipts to atomic PostgreSQL approval consumption."""
from __future__ import annotations

from datetime import datetime, timedelta

from apps.delivery_planner.approval import CurrentEvidence, require_return_approval
from apps.delivery_planner.planner import Plan
from apps.delivery_planner.trusted_identity import (
    SignedApprovalReceipt,
    canonical_plan_sha256,
)
from .services import commit_approved_plan


def commit_signed_approved_plan(
    *,
    receipt: SignedApprovalReceipt,
    evidence: CurrentEvidence,
    plan: Plan,
    verify_receipt,
):
    """Verify the signed MUFTI decision, then consume it with all plan intents.

    This is a provider-neutral bridge only. It does not issue approvals, fetch
    identity records, call a KMS, or dispatch a provider message.
    """
    if not isinstance(receipt, SignedApprovalReceipt):
        raise ValueError("signed_mufti_receipt_required")
    approved = require_return_approval(
        receipt=receipt, evidence=evidence, plan=plan,
        verify_receipt=verify_receipt,
    )
    try:
        expires_at = datetime.fromisoformat(receipt.expires_at.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid_signed_approval_expiry") from exc
    if expires_at.tzinfo is None or expires_at.utcoffset() != timedelta(0):
        raise ValueError("invalid_signed_approval_expiry")
    plan_fingerprint = canonical_plan_sha256(plan)
    if receipt.plan_sha256 != plan_fingerprint:
        raise ValueError("signed_approval_plan_mismatch")
    # Step idempotency keys are derived from exact part identities and included
    # in the canonical plan digest signed by the MUFTI.
    parts = tuple((step.ordinal, step.idempotency_key) for step in plan.steps)
    return commit_approved_plan(
        receipt_id=approved.receipt_id,
        nonce=receipt.nonce,
        approval_fingerprint=approved.approval_fingerprint,
        plan_fingerprint=plan_fingerprint,
        case_key=approved.case_key,
        answer_revision=plan.answer_revision,
        provider=plan.source_provider,
        expires_at=expires_at,
        parts=parts,
        verify_approval=lambda: True,
    )
