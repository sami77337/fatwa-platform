"""Synthetic composite adapter over the canonical case and signed delivery queue.

Internal staff APIs only. No routes, transport, signing key or production activation.
Capabilities are supplied by reviewed server configuration, never client fields.
"""

import os
from dataclasses import asdict, dataclass, replace
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.casework import delivery as legacy
from apps.casework import services as cases
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery
from apps.delivery_planner.trusted_identity import SignedApprovalReceipt, canonical_plan_sha256
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent, ProviderSignatureEvidence
from apps.delivery_queue.signed_provider_receipts import (
    audit_provider_reported_delivery,
    record_signed_provider_event,
    verify_stored_provider_evidence,
)

from .models import CompositeDelivery

SIMULATOR_PROVIDER = "composite-simulator"


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    capabilities: Capabilities
    max_media_bytes: int
    allowed_mime: frozenset[str]


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_COMPOSITE_DELIVERY_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("composite_delivery_disabled")


def _hash(value):
    return sha256(queue._canonical(value)).hexdigest()


def _profile(channel):
    reader = getattr(settings, "FATWA_COMPOSITE_DELIVERY_CAPABILITIES", None)
    try:
        profile = reader(channel)
    except Exception as exc:
        raise cases.CaseConflict("channel_capabilities_unavailable") from exc
    if not (
        isinstance(profile, ChannelProfile)
        and isinstance(profile.capabilities, Capabilities)
        and profile.capabilities.provider == SIMULATOR_PROVIDER
        and type(profile.max_media_bytes) is int
        and 1 <= profile.max_media_bytes <= 192000
        and type(profile.allowed_mime) is frozenset
        and 1 <= len(profile.allowed_mime) <= 16
        and all(type(mime) is str and 1 <= len(mime) <= 80 for mime in profile.allowed_mime)
    ):
        raise cases.CaseConflict("invalid_synthetic_channel_capabilities")
    return profile


def _profile_hash(profile):
    caps = asdict(profile.capabilities)
    caps["supported"] = sorted(caps["supported"])
    return _hash([caps, profile.max_media_bytes, sorted(profile.allowed_mime)])


def _prepare(case, subject_id, provider):
    decision, answer, base = legacy._current(case)
    legacy._approver(decision, cases._identity(provider, subject_id, case), provider)
    manifest = media.manifest_for_locked_answer(answer)
    if manifest is None:
        raise cases.CaseConflict("composite_manifest_required")
    origin = cases._delivery_origin_for_locked_case(case)
    profile = _profile(origin["channel"])
    capability_sha = _profile_hash(profile)
    evidence = replace(
        base, answer_sha256=manifest["sha256"], source_digest=_hash([base.source_digest, origin])
    )
    parts = tuple(
        Part(
            p["ordinal"],
            {"TEXT": "text", "FILE": "document", "AUDIO": "audio", "IMAGE": "image"}[p["kind"]],
            p["sha256"],
            len(answer.text) if p["kind"] == "TEXT" else p["size"],
        )
        for p in manifest["parts"]
    )
    target = "case-origin:" + _hash(
        [
            str(case.pk),
            case.requester_id,
            case.source.channel,
            case.source.source_event_id,
            origin,
        ]
    )
    plan = plan_delivery(
        case_key=case.public_ref,
        source_peer_key=target,
        parts=parts,
        capabilities=profile.capabilities,
        authority=Authority(answer.revision, evidence.answer_sha256, True),
        choice=Choice(),
    )
    steps = []
    for step, part in zip(plan.steps, manifest["parts"], strict=True):
        reason = step.reason
        action = step.action
        if not profile.capabilities.delivery_receipts:
            action, reason = "HUMAN_ACTION_REQUIRED", "signed_delivery_receipts_unavailable"
        elif part["kind"] != "TEXT" and (
            part["size"] > profile.max_media_bytes or part["media_type"] not in profile.allowed_mime
        ):
            action, reason = "HUMAN_ACTION_REQUIRED", "unsupported_mime_or_size"
        # The engine's payload digest is an envelope digest, not raw file SHA.
        # Pin raw hash, UUID, type, size, current decision/facts and full capability
        # values, including changes made without bumping a profile's version.
        key = _hash(
            [
                "composite-part.v1",
                step.idempotency_key,
                asdict(evidence),
                str(decision.pk),
                manifest["sha256"],
                capability_sha,
                part,
                action,
                reason,
            ]
        )
        steps.append(replace(step, action=action, reason=reason, idempotency_key=key))
    plan = replace(
        plan,
        steps=tuple(steps),
        status=(
            "PLANNED_NOT_SENT"
            if all(s.action == "READY_FOR_ADAPTER" for s in steps)
            else "REQUIRES_HUMAN_DECISION"
        ),
    )
    return decision, manifest, capability_sha, evidence, plan


def _reader(case, subject_id, provider, prepared):
    def read(case_key):
        fresh = _prepare(case, subject_id, provider)
        if case_key != case.public_ref or fresh != prepared:
            raise cases.CaseConflict("composite_context_changed")
        return fresh[3]

    return read


def prepare_composite_delivery(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    """Read-only full plan; unsupported parts remain visible for human action."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = _prepare(case, subject_id, provider)
        decision, manifest, capability_sha, evidence, plan = prepared
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return {
            "status": "REQUEST_NOT_APPROVED",
            "origin_channel": cases._delivery_origin_for_locked_case(case)["channel"],
            "decision_id": str(decision.pk),
            "manifest_sha256": manifest["sha256"],
            "capability_sha256": capability_sha,
            "parts": manifest["parts"],
            "evidence": asdict(evidence),
            "plan": asdict(plan),
            "plan_sha256": canonical_plan_sha256(plan),
        }


def stage_composite_delivery(
    *, case_id, subject_id, provider, receipt, verify_receipt, synthetic_fixtures_only=False
):
    """Signed return approval stages all parts atomically in the existing queue."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = _prepare(case, subject_id, provider)
        decision, manifest, capability_sha, evidence, plan = prepared
        if (
            not isinstance(receipt, SignedApprovalReceipt)
            or receipt.approver_id != decision.subject_id
        ):
            raise cases.CaseConflict("case_return_approver_mismatch")
        existing = CompositeDelivery.objects.filter(decision=decision).first()
        if existing and existing.approval_id != receipt.receipt_id:
            raise cases.CaseConflict("composite_delivery_already_bound")
        read = _reader(case, subject_id, provider, prepared)
        rows = adapter.commit_signed_approved_plan(
            receipt=receipt,
            evidence=evidence,
            plan=plan,
            verify_receipt=verify_receipt,
            read_current_evidence=read,
        )
        if existing is None:
            CompositeDelivery.objects.create(
                decision=decision,
                approval_id=receipt.receipt_id,
                manifest_sha256=manifest["sha256"],
                capability_sha256=capability_sha,
            )
        _bound(case, subject_id, provider)
        read(case.public_ref)
        return {
            "status": "STAGED_NOT_SENT"
            if all(r.state == "STAGED" for r in rows)
            else "ALREADY_RECORDED",
            "part_count": len(rows),
            "plan_sha256": canonical_plan_sha256(plan),
        }


def _bound(case, subject_id, provider):
    prepared = _prepare(case, subject_id, provider)
    decision, manifest, capability_sha, _, plan = prepared
    binding = CompositeDelivery.objects.select_related("approval").filter(decision=decision).first()
    if binding is None:
        raise cases.CaseConflict("composite_delivery_not_staged")
    if (
        binding.manifest_sha256 != manifest["sha256"]
        or binding.capability_sha256 != capability_sha
        or binding.approval.plan_fingerprint != canonical_plan_sha256(plan)
    ):
        raise cases.CaseConflict("composite_context_changed")
    return binding, prepared


def reserve_composite_part(
    *,
    case_id,
    subject_id,
    provider,
    worker_id,
    verify_worker,
    verify_receipt,
    synthetic_fixtures_only=False,
):
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        read = _reader(case, subject_id, provider, prepared)
        lease = adapter.reserve_signed_plan(
            plan_fingerprint=binding.approval.plan_fingerprint,
            worker_id=worker_id,
            verify_worker=verify_worker,
            verify_receipt=verify_receipt,
            read_current_evidence=read,
        )
        read(case.public_ref)
        return lease


def resolve_composite_part(
    *, case_id, subject_id, provider, lease, verify_receipt, synthetic_fixtures_only=False
):
    """Resolve exact bounded bytes internally; never expose a public asset URL."""
    _enabled()
    if not isinstance(lease, queue.WorkerLease):
        raise queue.QueueConflict("composite_lease_required")
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        read = _reader(case, subject_id, provider, prepared)
        intent = (
            DeliveryIntent.objects.select_for_update()
            .filter(
                pk=lease.intent_key,
                approval=binding.approval,
            )
            .first()
        )
        if intent is None or intent.state != "LEASED" or intent.lease_expires_at <= timezone.now():
            raise queue.QueueConflict("active_composite_lease_required")
        queue._authenticate_attempt(intent, lease)
        adapter._verify_current_claim(binding.approval, verify_receipt, read)
        queue._verify_locked_head(queue._locked_head())
        part = prepared[1]["parts"][intent.ordinal - 1]
        # Use answer_media's authorized reader so storage adapters can change
        # without teaching delivery about an inline column or storage location.
        if part["kind"] == "TEXT":
            raw = prepared[1]["text"].encode()
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
        return {**part, "raw": raw, "envelope_sha256": intent.payload_sha256}


def record_composite_event(
    *, case_id, subject_id, provider, lease, event, verifier, synthetic_fixtures_only=False
):
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        if getattr(event, "plan_fingerprint", None) != binding.approval.plan_fingerprint:
            raise cases.CaseConflict("composite_provider_plan_mismatch")
        result = record_signed_provider_event(lease=lease, event=event, verifier=verifier)
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return result


def composite_status(*, case_id, subject_id, provider, verifier, synthetic_fixtures_only=False):
    """Staff projection: queue state and cryptographic delivery proof are separate."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        fingerprint = binding.approval.plan_fingerprint
        summary = queue.summarize_plan(fingerprint)
        audit = audit_provider_reported_delivery(plan_fingerprint=fingerprint, verifier=verifier)
        rows = list(DeliveryIntent.objects.filter(approval=binding.approval).order_by("ordinal"))
        verified_intents = {
            row.pk
            for row in rows
            if row.state == "DELIVERED"
            and any(
                verify_stored_provider_evidence(receipt_reference=proof.pk, verifier=verifier)
                for proof in ProviderSignatureEvidence.objects.filter(
                    receipt__intent=row,
                    receipt__reported="DELIVERED",
                )[:4]
            )
        }
        parts = [
            {
                "id": part["id"],
                "ordinal": row.ordinal,
                "kind": part["kind"],
                "sha256": part["sha256"],
                "state": row.state,
                "delivery_verified": row.pk in verified_intents,
                "human_action": (row.state == "DELIVERED" and row.pk not in verified_intents)
                or row.state
                in {
                    "FAILED_REQUIRES_REVIEW",
                    "UNKNOWN_REQUIRES_RECONCILIATION",
                    "SENT_UNCONFIRMED",
                },
                "automatic_retry": False,
            }
            for part, row in zip(prepared[1]["parts"], rows, strict=True)
        ]
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return {
            "state": summary.state,
            "parts": parts,
            "expected_parts": summary.expected_parts,
            "verified_parts": min(audit.verified_delivered_parts, len(verified_intents)),
            "delivery_verified": audit.cryptographically_verified_complete
            and len(verified_intents) == summary.expected_parts,
            "evidence_status": audit.status,
            "read_confirmed": False,
            "human_action": any(p["human_action"] for p in parts)
            or summary.delivered_parts > min(audit.verified_delivered_parts, len(verified_intents)),
        }


def reconcile_composite_timeouts(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    """Explicit local reconciliation: quarantine elapsed leases, never resend."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        changed = queue.quarantine_expired_leases(
            plan_fingerprint=binding.approval.plan_fingerprint,
        )
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return {"unresolved_parts": len(changed), "automatic_retry": False}
