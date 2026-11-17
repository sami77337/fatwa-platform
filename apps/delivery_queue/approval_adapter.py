"""Signed MUFTI decisions to the owned PostgreSQL queue; no sender or keys."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest

from django.db import transaction
from django.utils import timezone

from apps.delivery_planner.approval import CurrentEvidence, require_return_approval
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Plan, Step, plan_delivery
from apps.delivery_planner.segmentation import TextSegment, parts_for_delivery
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier,
    SignedApprovalReceipt,
    canonical_plan_sha256,
)
from apps.platform_recovery.integration import mutation_service

from . import services as q
from .models import ApprovalClaim, DeliveryIntent, SignedDeliveryContext

SCHEMA = 'fatwa.signed-delivery-context.v1'


def _require_verifier(verifier):
    if not isinstance(verifier, Ed25519ApprovalVerifier):
        raise q.QueueConflict('trusted_ed25519_verifier_required')


def _sendable(plan):
    if (not isinstance(plan, Plan) or not q._ref(plan.case_key)
        or not q._ref(plan.source_provider, 64)
        or type(plan.answer_revision) is not int or plan.answer_revision < 1
        or type(plan.steps) is not tuple or not 1 <= len(plan.steps) <= 16
        or plan.status != 'PLANNED_NOT_SENT'):
        raise q.QueueConflict('sendable_plan_required')
    for number, step in enumerate(plan.steps, 1):
        if (not isinstance(step, Step) or type(step.ordinal) is not int or step.ordinal != number
            or step.action != 'READY_FOR_ADAPTER' or not q._hex(step.idempotency_key)
            or type(step.reason) is not str or len(step.reason) > 128):
            raise q.QueueConflict('human_delivery_decision_required')


def _read_evidence(reader, case_key):
    if not callable(reader):
        raise q.QueueConflict('current_evidence_reader_required')
    try:
        evidence = reader(case_key)
    except Exception as exc:
        raise q.QueueConflict('current_evidence_unavailable') from exc
    if not isinstance(evidence, CurrentEvidence) or evidence.case_key != case_key:
        raise q.QueueConflict('current_evidence_mismatch')
    return evidence


def _load_context(claim):
    saved = SignedDeliveryContext.objects.filter(approval=claim).first()
    if saved is None:
        raise q.QueueConflict('signed_context_required')
    try:
        envelope = saved.envelope
        raw = q._canonical(envelope)
        if (len(raw) > 32768 or type(envelope) is not dict
            or set(envelope) != {'schema', 'receipt', 'evidence', 'plan'}
            or envelope['schema'] != SCHEMA
            or not compare_digest(sha256(raw).hexdigest(), saved.envelope_sha256)):
            raise ValueError('invalid_context')
        receipt = SignedApprovalReceipt(**envelope['receipt'])
        baseline = CurrentEvidence(**envelope['evidence'])
        values = dict(envelope['plan'])
        if type(values.get('steps')) is not list or not 1 <= len(values['steps']) <= 16:
            raise ValueError('invalid_steps')
        values['steps'] = tuple(Step(**step) for step in values['steps'])
        plan = Plan(**values)
        _sendable(plan)
        expires = datetime.fromisoformat(receipt.expires_at.replace('Z', '+00:00'))
        if (claim.receipt_id != receipt.receipt_id or claim.case_key != receipt.case_key
            or claim.answer_revision != receipt.answer_revision
            or not compare_digest(claim.nonce_digest, sha256(receipt.nonce.encode()).hexdigest())
            or claim.expires_at != expires
            or not compare_digest(claim.plan_fingerprint, canonical_plan_sha256(plan))):
            raise ValueError('context_identity_mismatch')
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError) as exc:
        raise q.QueueConflict('signed_context_invalid') from exc
    return receipt, baseline, plan


def _verify_current_claim(claim, verify_receipt, read_current_evidence):
    _require_verifier(verify_receipt)
    receipt, baseline, plan = _load_context(claim)
    current = _read_evidence(read_current_evidence, claim.case_key)
    approved = require_return_approval(receipt=receipt, evidence=current,
        plan=plan, verify_receipt=verify_receipt)
    if current != baseline or not compare_digest(approved.approval_fingerprint, claim.approval_fingerprint):
        raise q.QueueConflict('approved_evidence_no_longer_current')
    rows = list(DeliveryIntent.objects.filter(approval=claim).order_by('ordinal'))
    q._validate_manifest(claim, rows)
    if any(row.provider != plan.source_provider or row.payload_sha256 != step.idempotency_key
           for row, step in zip(rows, plan.steps, strict=True)):
        raise q.QueueConflict('signed_plan_manifest_mismatch')
    return plan


@mutation_service
def commit_signed_approved_plan(*, receipt, evidence, plan, verify_receipt, read_current_evidence=None):
    """Reverify after acquiring commit locks; preserve the existing fixture API.

    The optional-reader form is retained for fixed synthetic callers only.
    Reservations and content resolution always require a live evidence reader.
    """
    if not isinstance(receipt, SignedApprovalReceipt):
        raise ValueError('signed_mufti_receipt_required')
    _require_verifier(verify_receipt)
    _sendable(plan)
    if read_current_evidence is not None and not callable(read_current_evidence):
        raise q.QueueConflict('current_evidence_reader_required')
    approved = require_return_approval(receipt=receipt, evidence=evidence,
        plan=plan, verify_receipt=verify_receipt)
    expires = datetime.fromisoformat(receipt.expires_at.replace('Z', '+00:00'))
    # Normalize tuples to JSON lists once so persisted/replayed envelopes agree.
    context = json.loads(q._canonical({'schema': SCHEMA, 'receipt': asdict(receipt),
        'evidence': asdict(evidence), 'plan': asdict(plan)}))

    def verify_after_lock():
        current = evidence if read_current_evidence is None else _read_evidence(read_current_evidence, plan.case_key)
        bound = require_return_approval(receipt=receipt, evidence=current,
            plan=plan, verify_receipt=verify_receipt)
        return current == evidence and compare_digest(bound.approval_fingerprint, approved.approval_fingerprint)

    return q.commit_approved_plan(receipt_id=receipt.receipt_id, nonce=receipt.nonce,
        approval_fingerprint=approved.approval_fingerprint,
        plan_fingerprint=canonical_plan_sha256(plan), case_key=plan.case_key,
        answer_revision=plan.answer_revision, provider=plan.source_provider, expires_at=expires,
        parts=tuple((step.ordinal, step.idempotency_key) for step in plan.steps),
        verify_approval=verify_after_lock, signed_context=context)


@mutation_service
def reserve_signed_plan(*, plan_fingerprint, worker_id, verify_worker, verify_receipt,
                        read_current_evidence, lease_seconds=60):
    """Authorize this worker for this plan, then recheck signed current evidence."""
    if (not q._hex(plan_fingerprint) or not q._ref(worker_id)
        or not callable(verify_worker) or not callable(read_current_evidence)):
        raise q.QueueConflict('invalid_trusted_worker_request')
    _require_verifier(verify_receipt)
    q._verify(lambda: verify_worker(worker_id, plan_fingerprint), no_argument=True,
              error='worker_not_authorized_for_plan')
    q._postgres_only()
    claim = ApprovalClaim.objects.filter(plan_fingerprint=plan_fingerprint).first()
    if claim is None:
        raise q.QueueConflict('signed_plan_not_found')
    _, _, plan = _load_context(claim)

    def current(locked_claim):
        _verify_current_claim(locked_claim, verify_receipt, read_current_evidence)
        return True

    return q.claim_next(provider=plan.source_provider, worker_id=worker_id,
        plan_fingerprint=plan_fingerprint, lease_seconds=lease_seconds, verify_claim=current)


@dataclass(frozen=True, slots=True)
class PreparedTextReturn:
    title: str
    source_peer_key: str
    capabilities: Capabilities
    evidence: CurrentEvidence
    explicit_human_choice: bool
    plan: Plan
    segments: tuple[TextSegment, ...]


@mutation_service
def prepare_text_return(*, title, body, evidence, source_peer_key, capabilities,
                        explicit_human_choice=False):
    """Pure preview: keep the body exact and bind title+body to human evidence.

    The title participates in approval identity; it is not silently prefixed to
    the message. No text is persisted or sent by this function.
    """
    if (type(title) is not str or len(title) > 500 or type(body) is not str
        or not 1 <= len(body) <= 6000 or not isinstance(evidence, CurrentEvidence)
        or not q._ref(source_peer_key) or not isinstance(capabilities, Capabilities)
        or type(explicit_human_choice) is not bool
        or any(value is not False for value in (evidence.source_deleted,
             evidence.clarification_pending, evidence.change_request_open))):
        raise q.QueueConflict('invalid_text_return_context')
    try:
        digest = sha256(json.dumps(['human-answer-content.v1', title, body],
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    except UnicodeError as exc:
        raise q.QueueConflict('invalid_text_encoding') from exc
    if not q._hex(evidence.answer_sha256) or not compare_digest(digest, evidence.answer_sha256):
        raise q.QueueConflict('human_answer_evidence_mismatch')
    parts, segments = parts_for_delivery(body, capabilities, explicit_human_choice=explicit_human_choice)
    plan = plan_delivery(case_key=evidence.case_key, source_peer_key=source_peer_key,
        parts=parts, capabilities=capabilities,
        authority=Authority(evidence.answer_revision, evidence.answer_sha256, True), choice=Choice())
    _sendable(plan)
    return PreparedTextReturn(title, source_peer_key, capabilities, evidence,
                              explicit_human_choice, plan, segments)


@mutation_service
def resolve_reserved_text(*, lease, prepared, verify_receipt, read_current_evidence):
    """Read-only final readiness check, not a network dispatch or send permit."""
    if (not isinstance(lease, q.WorkerLease) or not q._hex(lease.intent_key)
        or type(lease.token) is not str or not 32 <= len(lease.token) <= 128
        or not isinstance(prepared, PreparedTextReturn) or type(prepared.segments) is not tuple
        or not 1 <= len(prepared.segments) <= 16
        or any(not isinstance(segment, TextSegment) for segment in prepared.segments)):
        raise q.QueueConflict('invalid_reserved_text_request')
    _require_verifier(verify_receipt)
    rebuilt = prepare_text_return(title=prepared.title,
        body=''.join(segment.exact_text for segment in prepared.segments), evidence=prepared.evidence,
        source_peer_key=prepared.source_peer_key, capabilities=prepared.capabilities,
        explicit_human_choice=prepared.explicit_human_choice)
    if rebuilt != prepared:
        raise q.QueueConflict('prepared_text_was_changed')
    q._postgres_only()
    with transaction.atomic():
        intent = DeliveryIntent.objects.select_for_update(of=('self',)).select_related('approval').filter(pk=lease.intent_key).first()
        if intent is None or intent.state != 'LEASED':
            raise q.QueueConflict('active_text_lease_required')
        q._authenticate_attempt(intent, lease)
        if intent.lease_expires_at <= timezone.now():
            raise q.QueueConflict('text_lease_expired')
        approved_plan = _verify_current_claim(intent.approval, verify_receipt, read_current_evidence)
        if approved_plan != prepared.plan:
            raise q.QueueConflict('prepared_plan_does_not_match_approval')
        q._verify_locked_head(q._locked_head())
        return prepared.segments[intent.ordinal - 1]
