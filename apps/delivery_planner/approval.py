"""Fail-closed return-to-origin approval boundary.

This module never issues approvals or checks live accounts. A trusted identity
adapter must verify the approval receipt against the MUFTI account. Merely
showing a technical review or having a Python boolean is not an approval.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
import json
import re
from typing import Callable

from .planner import Authority, InvalidPlan, Plan

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    case_key: str
    answer_revision: int
    answer_sha256: str
    source_digest: str
    reply_digest: str
    approver_id: str
    approver_role: str
    decision: str
    receipt_id: str
    issued_at: str


@dataclass(frozen=True, slots=True)
class CurrentEvidence:
    case_key: str
    answer_revision: int
    answer_sha256: str
    source_digest: str
    reply_digest: str
    source_deleted: bool = False
    clarification_pending: bool = False
    change_request_open: bool = False


@dataclass(frozen=True, slots=True)
class ApprovedForReturn:
    authority: Authority
    approval_fingerprint: str
    receipt_id: str
    case_key: str
    source_digest: str
    reply_digest: str


def _digest(value: str, *, optional: bool = False) -> bool:
    return type(value) is str and (optional and value == "" or _SHA.fullmatch(value) is not None)


def _identifier(value: str, limit: int = 128) -> bool:
    return type(value) is str and len(value) <= limit and _ID.fullmatch(value) is not None


def _utc(value: str) -> bool:
    if type(value) is not str or len(value) > 40:
        return False
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0


def require_return_approval(
    *,
    receipt: ApprovalReceipt,
    evidence: CurrentEvidence,
    plan: Plan,
    verify_receipt: Callable[[ApprovalReceipt], bool],
) -> ApprovedForReturn:
    """Bind a verified MUFTI decision to the current exact answer and evidence.

    The application must provide a trusted verifier for the receipt's signature,
    actor membership and revocation status. No untrusted request-supplied
    "verified=True" flag is accepted. A technical reviewer is not a MUFTI.
    """
    if not isinstance(receipt, ApprovalReceipt) or not isinstance(evidence, CurrentEvidence):
        raise InvalidPlan("missing_owner_approval_evidence")
    if not isinstance(plan, Plan) or not callable(verify_receipt):
        raise InvalidPlan("missing_trusted_approval_verifier")
    if not (
        _identifier(receipt.case_key)
        and _identifier(receipt.approver_id)
        and _identifier(receipt.receipt_id)
        and type(receipt.answer_revision) is int and receipt.answer_revision > 0
        and _digest(receipt.answer_sha256)
        and _digest(receipt.source_digest)
        and _digest(receipt.reply_digest, optional=True)
        and _utc(receipt.issued_at)
        and receipt.approver_role == "MUFTI"
        and receipt.decision == "APPROVE_RETURN_TO_ORIGIN"
    ):
        raise InvalidPlan("invalid_or_non_mufti_approval")
    if (
        receipt.case_key != evidence.case_key
        or receipt.answer_revision != evidence.answer_revision
        or not _digest(evidence.answer_sha256)
        or not _digest(evidence.source_digest)
        or not _digest(evidence.reply_digest, optional=True)
        or not compare_digest(receipt.answer_sha256, evidence.answer_sha256)
        or not compare_digest(receipt.source_digest, evidence.source_digest)
        or not compare_digest(receipt.reply_digest, evidence.reply_digest)
        or evidence.source_deleted is not False
        or evidence.clarification_pending is not False
        or evidence.change_request_open is not False
        or plan.case_key != receipt.case_key
        or plan.answer_revision != receipt.answer_revision
    ):
        raise InvalidPlan("approval_not_bound_to_current_evidence")
    try:
        verified = verify_receipt(receipt)
    except Exception as exc:
        raise InvalidPlan("approval_verifier_unavailable") from exc
    if verified is not True:
        raise InvalidPlan("approval_signature_or_identity_not_verified")
    canonical = [
        receipt.case_key, receipt.answer_revision, receipt.answer_sha256,
        receipt.source_digest, receipt.reply_digest,
        receipt.approver_id, receipt.approver_role, receipt.decision,
        receipt.receipt_id, receipt.issued_at,
    ]
    fingerprint = sha256(json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return ApprovedForReturn(
        authority=Authority(receipt.answer_revision, receipt.answer_sha256, True),
        approval_fingerprint=fingerprint,
        receipt_id=receipt.receipt_id,
        case_key=receipt.case_key,
        source_digest=receipt.source_digest,
        reply_digest=receipt.reply_digest,
    )
