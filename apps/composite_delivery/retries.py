"""Explicit bounded successors in the existing queue, with preserved failure proof."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.editor_boundary import EditorBoundary
from apps.casework import delivery as legacy
from apps.casework import services as cases
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier,
    SignedApprovalReceipt,
    canonical_plan_sha256,
)
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent, ProviderSignatureEvidence
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    audit_provider_reported_delivery,
    verify_stored_provider_evidence,
)
from apps.platform_recovery.integration import mutation_service

from . import services
from .models import CompositeRetry

MAX_RETRIES = 3


def enabled():
    return getattr(settings, "FATWA_COMPOSITE_RETRY_ENABLED", False) is True


def _enabled():
    services._enabled()
    if not enabled():
        raise cases.CaseConflict("composite_retry_disabled")


def present(binding):
    return CompositeRetry.objects.filter(delivery=binding).exists()


def _verifier(verifier=None):
    current = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
    if not isinstance(current, Ed25519ProviderEventVerifier) or (
        verifier is not None and verifier is not current
    ):
        raise cases.CaseConflict("composite_retry_current_verifier_required")
    return current


def _trust(verifier):
    """Pure key/configuration pins after callbacks; no untrusted receipt keys."""
    return (
        id(_verifier(verifier)),
        tuple(sorted((name, key.public_bytes_raw()) for name, key in verifier._keys.items())),
        verifier._revoked_ids,
        id(verifier._key_status),
        verifier._issuer,
        verifier._audience,
        verifier._provider,
        id(verifier._clock),
        verifier._max_age,
        verifier._max_lifetime,
    )


def _approval_trust():
    verifier = getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None)
    if not isinstance(verifier, Ed25519ApprovalVerifier):
        return (id(verifier),)
    return (
        id(verifier),
        tuple(sorted((name, key.public_bytes_raw()) for name, key in verifier._keys.items())),
        verifier._revoked_key_ids,
        verifier._issuer,
        verifier._audience,
        id(verifier._identity_lookup),
        id(verifier._is_revoked_or_consumed),
        id(verifier._clock),
        verifier._max_age,
        verifier._max_lifetime,
    )


def _approval_verifier(verifier):
    adapter._require_verifier(verifier)
    if verifier is not getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None):
        raise cases.CaseConflict("composite_retry_current_approval_verifier_required")


@contextmanager
def boundary(*, case_id, subject_id, provider, selection_mode=None, synthetic_fixtures_only=False):
    """Retain the current case, identity and provider trust through native render."""
    _enabled()
    identity = services._choice_identity(provider)
    verifier = _verifier()
    trust = _trust(verifier)
    approval_trust = _approval_trust()
    editor = EditorBoundary(provider)
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = services._prepare(case, subject_id, provider, selection_mode)
        yield
        services._reader(case, subject_id, provider, prepared)(case.public_ref)
        editor.check(cases._identity(provider, subject_id, case))
        _enabled()
        if (
            services._choice_identity(provider) != identity
            or _trust(verifier) != trust
            or _approval_trust() != approval_trust
        ):
            raise cases.CaseConflict("composite_retry_trust_changed")


def _failure(intent, verifier, reference=None):
    if intent.state != "FAILED_REQUIRES_REVIEW":
        raise cases.CaseConflict("composite_retry_requires_failed_part")
    proofs = ProviderSignatureEvidence.objects.select_related("receipt").filter(
        receipt__intent=intent, receipt__reported="FAILED"
    )
    if reference is not None:
        proofs = proofs.filter(pk=reference)
    for proof in proofs.order_by("pk")[:4]:
        if verify_stored_provider_evidence(receipt_reference=proof.pk, verifier=verifier):
            return proof
    raise cases.CaseConflict("composite_retry_signed_failure_required")


def _issued(receipt):
    try:
        value = datetime.fromisoformat(receipt.issued_at)
    except (ValueError, TypeError, AttributeError):
        raise cases.CaseConflict("composite_retry_fresh_approval_required") from None
    if not queue._utc(value):
        raise cases.CaseConflict("composite_retry_fresh_approval_required")
    return value


def _scope(binding, part, parent, proof, number, request_id):
    full = media.manifest_for_locked_answer(binding.decision.answer)
    if full is None or full["sha256"] != binding.manifest_sha256:
        raise cases.CaseConflict("composite_retry_manifest_changed")
    return {
        "schema": "fatwa.composite-retry.v1",
        "request_id": str(request_id),
        "decision_id": str(binding.decision_id),
        "root_plan": binding.approval.plan_fingerprint,
        "parent_intent": parent.pk,
        "parent_plan": parent.plan_fingerprint,
        "logical_ordinal": part["ordinal"],
        "queue_ordinal": 1,
        "retry_number": number,
        "max_retries": MAX_RETRIES,
        "part": part,
        "full_manifest": full["parts"],
        "selection_mode": binding.selection_mode,
        "manifest_sha256": binding.manifest_sha256,
        "capability_sha256": binding.capability_sha256,
        "failure_evidence": proof.pk,
        "failure_sha256": proof.envelope_sha256,
        "reviewer": {
            "subject_id": binding.decision.subject_id,
            "provider_id": binding.decision.provider_id,
            "auth_epoch": binding.decision.auth_epoch,
        },
        "origin": cases._delivery_origin_for_locked_case(binding.decision.case),
    }


def _plan(binding, part, scope):
    _, baseline, original = adapter._load_context(binding.approval)
    step = original.steps[part["ordinal"] - 1]
    # The queue ordinal is explicitly local to a one-part plan. The signed
    # scope retains the original ordinal, UUID, bytes and complete manifest.
    step = replace(
        step,
        ordinal=1,
        idempotency_key=services._hash(["composite-retry.part.v1", step.idempotency_key, scope]),
    )
    evidence = replace(
        baseline,
        source_digest=services._hash(
            ["composite-retry.evidence.v1", baseline.source_digest, scope]
        ),
    )
    return evidence, replace(original, steps=(step,))


def chains(binding, verifier):
    """Validate exact historical ancestry without relabeling original queue state."""
    _enabled()
    verifier = _verifier(verifier)
    queue._verify_locked_head(queue._locked_head())
    manifest = media.manifest_for_locked_answer(binding.decision.answer)
    if manifest is None or manifest["sha256"] != binding.manifest_sha256:
        raise cases.CaseConflict("composite_retry_manifest_changed")
    parts = manifest["parts"] if binding.selection_mode == "ALL" else manifest["parts"][:1]
    roots = list(DeliveryIntent.objects.filter(approval=binding.approval).order_by("ordinal"))
    queue._validate_manifest(binding.approval, roots)
    if len(parts) != len(roots):
        raise cases.CaseConflict("composite_retry_root_manifest_changed")
    retries = list(
        CompositeRetry.objects.filter(delivery=binding)
        .select_related("approval", "failure_evidence__receipt")
        .order_by("logical_ordinal", "retry_number")
    )
    by_parent = {row.parent_intent_id: row for row in retries}
    seen, result = set(), []
    for part, root in zip(parts, roots, strict=True):
        current, history = root, []
        while current.pk in by_parent:
            row = by_parent[current.pk]
            number = len(history) + 1
            if number > MAX_RETRIES or row.pk in seen:
                raise cases.CaseConflict("composite_retry_history_invalid")
            proof = _failure(current, verifier, row.failure_evidence_id)
            expected = _scope(binding, part, current, proof, number, row.pk)
            payload = queue._canonical(expected).decode()
            if (
                row.scope != expected
                or row.canonical_payload != payload
                or row.sha256 != sha256(payload.encode()).hexdigest()
                or row.logical_ordinal != part["ordinal"]
                or str(row.part_id) != part["id"]
                or row.retry_number != number
            ):
                raise cases.CaseConflict("composite_retry_history_invalid")
            evidence, plan = _plan(binding, part, expected)
            receipt, saved_evidence, saved_plan = adapter._load_context(row.approval)
            children = list(DeliveryIntent.objects.filter(approval=row.approval))
            queue._validate_manifest(row.approval, children)
            if (
                len(children) != 1
                or saved_evidence != evidence
                or saved_plan != plan
                or receipt.approver_id != binding.decision.subject_id
                or _issued(receipt) < proof.receipt.recorded_at
                or children[0].ordinal != 1
                or children[0].payload_sha256 != plan.steps[0].idempotency_key
            ):
                raise cases.CaseConflict("composite_retry_signed_context_changed")
            history.append((row, current))
            seen.add(row.pk)
            current = children[0]
        result.append({"part": part, "root": root, "leaf": current, "history": history})
    if len(seen) != len(retries):
        raise cases.CaseConflict("composite_retry_disconnected_history")
    return result


def _proposal(case, subject_id, provider, *, parent_intent, request_id, verifier):
    _enabled()
    services._choice_identity(provider)
    request_id = cases._uuid(request_id)
    binding, prepared = services._bound(case, subject_id, provider)
    history = chains(binding, verifier)
    selected = None
    existing = CompositeRetry.objects.filter(pk=request_id).first()
    for chain in history:
        if chain["leaf"].pk == parent_intent:
            selected = (chain["part"], chain["leaf"], len(chain["history"]) + 1)
        for row, parent in chain["history"]:
            if parent.pk == parent_intent:
                if row.pk != request_id:
                    raise cases.CaseConflict("composite_retry_parent_already_bound")
                selected = (chain["part"], parent, row.retry_number)
    if selected is None:
        raise cases.CaseConflict("composite_retry_parent_not_in_current_plan")
    part, parent, number = selected
    if existing and (existing.delivery_id != binding.pk or existing.parent_intent_id != parent.pk):
        raise cases.CaseConflict("composite_retry_request_already_used")
    if number > MAX_RETRIES:
        raise cases.CaseConflict("composite_retry_limit_reached")
    proof = _failure(parent, verifier, existing.failure_evidence_id if existing else None)
    scope = _scope(binding, part, parent, proof, number, request_id)
    evidence, plan = _plan(binding, part, scope)
    services._reader(case, subject_id, provider, prepared)(case.public_ref)
    return binding, prepared, scope, evidence, plan, proof, existing


def _reader(case, subject_id, provider, proposal, verifier):
    expected = proposal[2:5]

    def read(case_key):
        fresh = _proposal(
            case,
            subject_id,
            provider,
            parent_intent=proposal[2]["parent_intent"],
            request_id=proposal[2]["request_id"],
            verifier=verifier,
        )
        if case_key != case.public_ref or fresh[2:5] != expected:
            raise cases.CaseConflict("composite_retry_context_changed")
        return fresh[3]

    return read


@mutation_service
def prepare_retry(
    *, case_id, subject_id, provider, parent_intent, request_id, synthetic_fixtures_only=False
):
    common = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with boundary(**common):
        with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            _,
        ):
            proposal = _proposal(
                case,
                subject_id,
                provider,
                parent_intent=parent_intent,
                request_id=request_id,
                verifier=_verifier(),
            )
            return {
                "status": "REQUEST_NOT_APPROVED",
                "retry": proposal[2],
                "evidence": asdict(proposal[3]),
                "plan": asdict(proposal[4]),
                "plan_sha256": canonical_plan_sha256(proposal[4]),
                "automatic_retry": False,
            }


@mutation_service
def stage_retry(
    *,
    case_id,
    subject_id,
    provider,
    parent_intent,
    request_id,
    receipt,
    verify_receipt,
    synthetic_fixtures_only=False,
):
    _approval_verifier(verify_receipt)
    common = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with boundary(**common):
        with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            _,
        ):
            verifier = _verifier()
            proposal = _proposal(
                case,
                subject_id,
                provider,
                parent_intent=parent_intent,
                request_id=request_id,
                verifier=verifier,
            )
            binding, prepared, scope, evidence, plan, proof, existing = proposal
            if (
                not isinstance(receipt, SignedApprovalReceipt)
                or receipt.approver_id != binding.decision.subject_id
                or _issued(receipt) < proof.receipt.recorded_at
            ):
                raise cases.CaseConflict("composite_retry_fresh_approval_required")
            if existing and existing.approval_id != receipt.receipt_id:
                raise cases.CaseConflict("composite_retry_parent_already_bound")
            read = _reader(case, subject_id, provider, proposal, verifier)
            adapter.commit_signed_approved_plan(
                receipt=receipt,
                evidence=evidence,
                plan=plan,
                verify_receipt=verify_receipt,
                read_current_evidence=read,
            )
            if existing is None:
                payload = queue._canonical(scope).decode()
                existing = CompositeRetry.objects.create(
                    id=request_id,
                    delivery=binding,
                    parent_intent_id=parent_intent,
                    approval_id=receipt.receipt_id,
                    part_id=scope["part"]["id"],
                    failure_evidence=proof,
                    logical_ordinal=scope["logical_ordinal"],
                    retry_number=scope["retry_number"],
                    scope=scope,
                    canonical_payload=payload,
                    sha256=sha256(payload.encode()).hexdigest(),
                )
            read(case.public_ref)
            return {
                "status": "RETRY_RECORDED_NOT_SENT",
                "retry_id": str(existing.pk),
                "plan_sha256": canonical_plan_sha256(plan),
                "part_id": str(existing.part_id),
                "logical_ordinal": existing.logical_ordinal,
                "queue_ordinal": 1,
                "retry_number": existing.retry_number,
                "automatic_retry": False,
            }


def _bound_retry(case, subject_id, provider, intent, verifier):
    row = (
        CompositeRetry.objects.select_related("approval")
        .filter(approval_id=intent.approval_id)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("composite_retry_unknown_plan")
    proposal = _proposal(
        case,
        subject_id,
        provider,
        parent_intent=row.parent_intent_id,
        request_id=row.pk,
        verifier=verifier,
    )
    if row.delivery_id != proposal[0].pk:
        raise cases.CaseConflict("composite_retry_wrong_case")
    return row, proposal, _reader(case, subject_id, provider, proposal, verifier)


def reserve_next(*, case, subject_id, provider, binding, worker_id, verify_worker, verify_receipt):
    _approval_verifier(verify_receipt)
    verifier = _verifier()
    with boundary(
        case_id=case.pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
    ):
        for chain in chains(binding, verifier):
            intent = chain["leaf"]
            if not chain["history"] or intent.state != "STAGED":
                continue
            row, _, read = _bound_retry(case, subject_id, provider, intent, verifier)
            lease = adapter.reserve_signed_plan(
                plan_fingerprint=row.approval.plan_fingerprint,
                worker_id=worker_id,
                verify_worker=verify_worker,
                verify_receipt=verify_receipt,
                read_current_evidence=read,
            )
            read(case.public_ref)
            if lease is not None:
                return lease
    return None


def resolve_locked(*, case, subject_id, provider, lease, intent, verify_receipt):
    _approval_verifier(verify_receipt)
    with boundary(
        case_id=case.pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
    ):
        row, proposal, read = _bound_retry(case, subject_id, provider, intent, _verifier())
        if intent.state != "LEASED" or intent.lease_expires_at <= timezone.now():
            raise queue.QueueConflict("active_composite_retry_lease_required")
        queue._authenticate_attempt(intent, lease)
        adapter._verify_current_claim(row.approval, verify_receipt, read)
        part = proposal[2]["part"]
        if part["kind"] == "TEXT":
            raw = proposal[1][1]["text"].encode()
        else:
            resolved = media.staff_read(
                part_id=part["id"],
                subject_id=subject_id,
                provider=provider,
                synthetic_fixtures_only=True,
            )
            if {key: resolved[key] for key in part} != part:
                raise cases.CaseConflict("composite_content_changed")
            raw = resolved["raw"]
        if sha256(raw).hexdigest() != part["sha256"] or len(raw) != part["size"]:
            raise cases.CaseConflict("composite_content_changed")
        read(case.public_ref)
        return {
            **part,
            "raw": raw,
            "queue_ordinal": 1,
            "retry_id": str(row.pk),
            "envelope_sha256": intent.payload_sha256,
        }


def record_locked(*, case, subject_id, provider, lease, event, verifier):
    with boundary(
        case_id=case.pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
    ):
        intent = DeliveryIntent.objects.select_for_update().filter(pk=lease.intent_key).first()
        if (
            intent is None
            or event.intent_key != intent.pk
            or event.plan_fingerprint != intent.plan_fingerprint
        ):
            raise cases.CaseConflict("composite_retry_provider_plan_mismatch")
        _, _, read = _bound_retry(case, subject_id, provider, intent, _verifier(verifier))
        result = services.record_signed_provider_event(lease=lease, event=event, verifier=verifier)
        read(case.public_ref)
        return result


def status_locked(binding, verifier):
    history = chains(binding, verifier)
    original = queue.summarize_plan(binding.approval.plan_fingerprint)
    original_audit = audit_provider_reported_delivery(
        plan_fingerprint=binding.approval.plan_fingerprint, verifier=verifier
    )
    parts, plans = [], {binding.approval.plan_fingerprint}
    for chain in history:
        row, part = chain["leaf"], chain["part"]
        verified = row.state == "DELIVERED" and any(
            verify_stored_provider_evidence(receipt_reference=proof.pk, verifier=verifier)
            for proof in ProviderSignatureEvidence.objects.filter(
                receipt__intent=row, receipt__reported="DELIVERED"
            )[:4]
        )
        ancestors = []
        for retry, parent in chain["history"]:
            plans.add(retry.approval.plan_fingerprint)
            ancestors.append(
                {
                    "retry_id": str(retry.pk),
                    "retry_number": retry.retry_number,
                    "failed_intent": parent.pk,
                    "failure_evidence": retry.failure_evidence_id,
                    "failed_state": parent.state,
                    "plan_sha256": retry.approval.plan_fingerprint,
                }
            )
        retry_allowed = False
        if row.state == "FAILED_REQUIRES_REVIEW" and len(ancestors) < MAX_RETRIES:
            try:
                _failure(row, verifier)
                retry_allowed = True
            except cases.CaseConflict:
                pass
        parts.append(
            {
                "id": part["id"],
                "ordinal": part["ordinal"],
                "kind": part["kind"],
                "sha256": part["sha256"],
                "state": row.state,
                "intent_key": row.pk,
                "queue_ordinal": row.ordinal,
                "delivery_verified": bool(verified),
                "automatic_retry": False,
                "may_retry": retry_allowed,
                "retry_count": len(ancestors),
                "retry_history": ancestors,
                "original_state": chain["root"].state,
                "human_action": row.state
                in {"FAILED_REQUIRES_REVIEW", "UNKNOWN_REQUIRES_RECONCILIATION", "SENT_UNCONFIRMED"}
                or (row.state == "DELIVERED" and not verified),
            }
        )
    counts = Counter(part["state"] for part in parts)
    verified = sum(part["delivery_verified"] for part in parts)
    if counts["DELIVERED"] == len(parts):
        state = "DELIVERED"
    elif counts["UNKNOWN_REQUIRES_RECONCILIATION"]:
        state = "NEEDS_RECONCILIATION"
    elif counts["FAILED_REQUIRES_REVIEW"]:
        state = "PARTIALLY_FAILED" if counts["DELIVERED"] else "FAILED_REQUIRES_REVIEW"
    elif counts["DELIVERED"]:
        state = "PARTIALLY_DELIVERED"
    elif counts["LEASED"] or counts["SENT_UNCONFIRMED"]:
        state = "IN_PROGRESS"
    else:
        state = "STAGED"
    complete = verified == len(parts)
    return {
        "state": state,
        "parts": parts,
        "expected_parts": len(parts),
        "verified_parts": verified,
        "delivery_verified": complete,
        "evidence_status": "PROVIDER_REPORTED_DELIVERY_VERIFIED"
        if complete
        else "NOT_FULLY_DELIVERED",
        "read_confirmed": False,
        "human_action": any(part["human_action"] for part in parts),
        "original_plan": {
            "plan_sha256": original.plan_fingerprint,
            "state": original.state,
            "delivery_verified": original_audit.cryptographically_verified_complete,
        },
        "retained_plans": sorted(plans),
        "max_retries": MAX_RETRIES,
    }
