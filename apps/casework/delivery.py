"""Synthetic case → signed Mufti return approval → existing delivery evidence.

No signer, sender or public endpoint. Lock order is case, then queue audit head.
All text/target/evidence is reconstructed from the case, never caller payloads.
"""

import json
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256

from apps.data_privacy import integration as privacy
from apps.delivery_planner.approval import CurrentEvidence
from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import SignedApprovalReceipt, canonical_plan_sha256
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    audit_provider_reported_delivery,
    record_signed_provider_event,
)
from apps.platform_recovery.integration import mutation_service

from . import services as cases
from .models import CaseDelivery

CHANNEL = "website"
PROFILE = "casework-synthetic.v1"


@contextmanager
def _staff_case(case_id, subject_id, provider, ack):
    if ack is not True:
        raise cases.CaseConflict("synthetic_ack_required")
    with queue.synthetic_queue_atomic():
        with cases._staff_case(case_id, subject_id, provider, ack) as current:
            yield current


@contextmanager
def _token_case(token, ack):
    if ack is not True:
        raise cases.CaseConflict("synthetic_ack_required")
    with queue.synthetic_queue_atomic():
        with cases._token_case(token, ack) as case:
            yield case


def _hash(value):
    return sha256(queue._canonical(value)).hexdigest()


def _current(case):
    case.refresh_from_db()
    cases._verify(case)
    if case.stage != "ANSWERED" or case.approved_answer_id is None:
        raise cases.CaseConflict("current_mufti_approval_required")
    answer = case.approved_answer
    # A case envelope grant cannot authorize its exact human answer. Both the
    # text-only and composite adapters reuse this boundary before constructing
    # a signed plan, reserving a part or resolving bytes for that plan.
    privacy.source("ANSWER", answer.pk)
    decision = answer.decision
    if (
        decision.action != "APPROVE"
        or decision.case_id != case.pk
        or decision.evidence_version != case.evidence_version
        or answer.evidence_version != case.evidence_version
        or answer.revision != case.answer_revision
    ):
        raise cases.CaseConflict("current_mufti_approval_required")
    cases._answer_citations(answer)
    cases._answer_annotations(answer)
    # Pin exact immutable identities as well as content. An identical answer
    # approved for different facts or by a later decision is a different scope.
    evidence = CurrentEvidence(
        case_key=case.public_ref,
        answer_revision=answer.revision,
        answer_sha256=sha256(
            json.dumps(
                ["human-answer-content.v1", "", answer.text],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        source_digest=_hash(
            [
                "casework-facts.v1",
                str(case.pk),
                case.source.source_event_id,
                case.source.question_sha256,
                case.evidence_version,
                list(case.evidence.order_by("version").values_list("version", "text_sha256")),
            ]
        ),
        reply_digest=_hash(
            [
                "casework-decision.v1",
                str(decision.pk),
                str(answer.pk),
                decision.evidence_version,
                decision.subject_id,
                decision.provider_id,
                decision.auth_epoch,
            ]
        ),
    )
    return decision, answer, evidence


def _prepare(case, *, max_chars, split):
    if type(max_chars) is not int or not 1 <= max_chars <= 6000 or type(split) is not bool:
        raise cases.CaseConflict("invalid_case_delivery_options")
    decision, answer, evidence = _current(case)
    origin = cases._delivery_origin_for_locked_case(case)
    if origin["channel"].lower() != "website":
        # This existing adapter has only a website capability contract. Imported
        # sources must use the source-aware composite plan or remain held.
        raise cases.CaseConflict("source_channel_requires_human_delivery")
    manifest = cases._answer_manifest(answer)
    if manifest and manifest["requires_human_delivery"]:
        # This adapter can represent text only. Never silently omit approved
        # files/audio or pretend the old provider receipt covers those bytes.
        raise cases.CaseConflict("unsupported_media_requires_human_action")
    prepared = adapter.prepare_text_return(
        title="",
        body=answer.text,
        evidence=evidence,
        source_peer_key="case-origin:"
        + _hash(
            [
                str(case.pk),
                case.requester_id,
                case.source.channel,
                case.source.source_event_id,
            ]
        ),
        capabilities=Capabilities(CHANNEL, PROFILE, frozenset({"text"}), max_chars, True),
        explicit_human_choice=split,
    )
    return decision, prepared


def _approver(decision, identity, provider):
    if (decision.subject_id, decision.provider_id, decision.auth_epoch) != (
        identity.subject_id,
        provider.provider_id,
        identity.auth_epoch,
    ):
        raise cases.CaseConflict("case_approver_identity_changed")


def _evidence_reader(case, decision, provider, subject_id):
    def current(case_key):
        fresh_decision, _, evidence = _current(case)
        _approver(fresh_decision, cases._identity(provider, subject_id, case), provider)
        if fresh_decision.pk != decision.pk or case_key != case.public_ref:
            raise cases.CaseConflict("case_delivery_evidence_changed")
        return evidence

    return current


@mutation_service
def prepare_case_delivery(
    *,
    case_id,
    subject_id,
    provider,
    max_chars=6000,
    split=False,
    synthetic_fixtures_only=False,
):
    """Read-only request for an external signed approval of the exact return plan.

    A stored scholarly APPROVE is necessary but does not itself authorize return.
    The caller receives internal plan/evidence, not a requester-facing response.
    """
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, prepared = _prepare(case, max_chars=max_chars, split=split)
        _approver(decision, identity, provider)
        return {
            "status": "REQUEST_NOT_APPROVED",
            "decision_id": str(decision.pk),
            "evidence": asdict(prepared.evidence),
            "plan": asdict(prepared.plan),
            "plan_sha256": canonical_plan_sha256(prepared.plan),
            "max_chars": max_chars,
            "split": split,
        }


@mutation_service
def stage_case_delivery(
    *,
    case_id,
    subject_id,
    provider,
    receipt,
    verify_receipt,
    max_chars=6000,
    split=False,
    synthetic_fixtures_only=False,
):
    """Atomically bind one signed return approval and queue manifest to a decision."""
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, prepared = _prepare(case, max_chars=max_chars, split=split)
        _approver(decision, identity, provider)
        if (
            not isinstance(receipt, SignedApprovalReceipt)
            or receipt.approver_id != decision.subject_id
        ):
            raise cases.CaseConflict("case_return_approver_mismatch")
        existing = CaseDelivery.objects.filter(decision=decision).first()
        if existing and (
            existing.approval_id != receipt.receipt_id
            or existing.max_chars != max_chars
            or existing.split != split
        ):
            raise cases.CaseConflict("case_delivery_already_bound")

        current = _evidence_reader(case, decision, provider, subject_id)
        rows = adapter.commit_signed_approved_plan(
            receipt=receipt,
            evidence=prepared.evidence,
            plan=prepared.plan,
            verify_receipt=verify_receipt,
            read_current_evidence=current,
        )
        current(case.public_ref)
        if existing is None:
            CaseDelivery.objects.create(
                decision=decision,
                approval_id=receipt.receipt_id,
                max_chars=max_chars,
                split=split,
            )
        return {
            "status": "STAGED_NOT_SENT"
            if all(row.state == "STAGED" for row in rows)
            else "ALREADY_RECORDED",
            "plan_sha256": canonical_plan_sha256(prepared.plan),
            "part_count": len(rows),
        }


def _bound(case):
    decision, _, _ = _current(case)
    binding = CaseDelivery.objects.select_related("approval").filter(decision=decision).first()
    if binding is None:
        raise cases.CaseConflict("case_delivery_not_staged")
    _, prepared = _prepare(case, max_chars=binding.max_chars, split=binding.split)
    receipt, baseline, plan = adapter._load_context(binding.approval)
    if (
        receipt.approver_id != decision.subject_id
        or baseline != prepared.evidence
        or plan != prepared.plan
        or binding.approval.case_key != case.public_ref
    ):
        raise cases.CaseConflict("case_delivery_binding_mismatch")
    return decision, binding, prepared


@mutation_service
def reserve_case_delivery(
    *,
    case_id,
    subject_id,
    provider,
    worker_id,
    verify_worker,
    verify_receipt,
    synthetic_fixtures_only=False,
):
    """Reserve an existing part with a fresh case/identity check; never dispatch."""
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, binding, _ = _bound(case)
        _approver(decision, identity, provider)

        current = _evidence_reader(case, decision, provider, subject_id)
        lease = adapter.reserve_signed_plan(
            plan_fingerprint=binding.approval.plan_fingerprint,
            worker_id=worker_id,
            verify_worker=verify_worker,
            verify_receipt=verify_receipt,
            read_current_evidence=current,
        )
        current(case.public_ref)
        return lease


@mutation_service
def resolve_case_delivery_text(
    *,
    case_id,
    subject_id,
    provider,
    lease,
    verify_receipt,
    synthetic_fixtures_only=False,
):
    """Resolve the exact reserved human text internally; this is not a send API."""
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, _, prepared = _bound(case)
        _approver(decision, identity, provider)

        current = _evidence_reader(case, decision, provider, subject_id)
        segment = adapter.resolve_reserved_text(
            lease=lease,
            prepared=prepared,
            verify_receipt=verify_receipt,
            read_current_evidence=current,
        )
        current(case.public_ref)
        return segment


@mutation_service
def record_case_provider_event(
    *,
    case_id,
    subject_id,
    provider,
    lease,
    event,
    verifier,
    synthetic_fixtures_only=False,
):
    """Attach an offline signed provider event only to the current bound decision."""
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        identity,
    ):
        decision, binding, _ = _bound(case)
        _approver(decision, identity, provider)
        if getattr(event, "plan_fingerprint", None) != binding.approval.plan_fingerprint:
            raise cases.CaseConflict("case_provider_plan_mismatch")
        result = record_signed_provider_event(lease=lease, event=event, verifier=verifier)
        _evidence_reader(case, decision, provider, subject_id)(case.public_ref)
        return result


def _requester_delivery_locked(case, verifier):
    """Project trusted delivery evidence while the requester case row is locked.

    Caller owns the case lock; the audit helper validates the existing queue
    snapshot without issuing a lease, sending content or exposing answer text.
    """
    result = {**cases._public(case), "delivery_status": "NOT_STAGED"}
    if case.stage != "ANSWERED":
        result["delivery_status"] = "CURRENT_APPROVAL_REQUIRED"
        return result
    from apps.data_privacy.integration import source as privacy
    from apps.data_privacy.services import PrivacyDenied

    try:
        privacy("ANSWER", case.approved_answer_id)
        cases._answer_citations(case.approved_answer)
        cases._answer_annotations(case.approved_answer)
        manifest = cases._answer_manifest(case.approved_answer)
    except PrivacyDenied:
        # Case access can remain valid while the exact answer or one of its
        # sources/parts is unavailable. Return no part count or source detail,
        # while keeping the independent requester conversation usable.
        result["delivery_status"] = "EVIDENCE_UNAVAILABLE"
        return result
    if manifest and manifest["requires_human_delivery"]:
        result["delivery_status"] = "UNSUPPORTED_MEDIA_REQUIRES_HUMAN_ACTION"
        return result
    if not CaseDelivery.objects.filter(decision__answer_id=case.approved_answer_id).exists():
        return result
    if not isinstance(verifier, Ed25519ProviderEventVerifier):
        result["delivery_status"] = "EVIDENCE_UNAVAILABLE"
        return result
    try:
        _, binding, _ = _bound(case)
        audit = audit_provider_reported_delivery(
            plan_fingerprint=binding.approval.plan_fingerprint,
            verifier=verifier,
        )
    except (cases.CaseConflict, queue.QueueConflict):
        result["delivery_status"] = "EVIDENCE_UNAVAILABLE"
        return result
    result.update(
        delivery_verified=audit.cryptographically_verified_complete,
        delivery_status=audit.status,
        expected_parts=audit.expected_parts,
        verified_parts=audit.verified_delivered_parts,
    )
    return result


@mutation_service
def requester_delivery_status(token, *, verifier=None, synthetic_fixtures_only=False):
    """Private read-only projection; the trusted verifier is server supplied.

    No text, PK, plan, approval, signature, worker or channel ID is exposed.
    """
    with _token_case(token, synthetic_fixtures_only) as case:
        return _requester_delivery_locked(case, verifier)
