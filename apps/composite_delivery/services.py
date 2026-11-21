"""Synthetic composite adapter over the canonical case and signed delivery queue.

Internal staff APIs only. No routes, transport, signing key or production activation.
Capabilities are supplied by reviewed server configuration, never client fields.
"""

import os
from contextlib import contextmanager
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
from apps.platform_recovery.integration import mutation_service

from .models import CompositeDelivery

SIMULATOR_PROVIDER = "composite-simulator"


def _choice_identity(provider):
    from apps.casework_web.access import RequestDirectory
    from apps.research_library.services import identity_snapshot

    configured = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if provider is not configured and not (
        isinstance(provider, RequestDirectory) and provider._provider is configured
    ):
        raise cases.CaseConflict("composite_current_directory_required")
    return identity_snapshot(provider), identity_snapshot(configured)


@contextmanager
def choice_boundary(
    *, case_id, subject_id, provider, selection_mode=None, synthetic_fixtures_only=False
):
    """Keep explicit selection pins and current identity through native render."""
    from apps.answer_media.editor_boundary import EditorBoundary

    _enabled()
    if getattr(settings, "FATWA_COMPOSITE_CHOICES_ENABLED", False) is not True:
        raise cases.CaseConflict("composite_selection_disabled")
    trust = _choice_identity(provider)
    before = EditorBoundary(provider)
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        actor,
    ):
        prepared = _prepare(case, subject_id, provider, selection_mode)
        yield
        _enabled()
        if getattr(settings, "FATWA_COMPOSITE_CHOICES_ENABLED", False) is not True:
            raise cases.CaseConflict("composite_selection_disabled")
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        before.check(cases._identity(provider, subject_id, case))
        if _choice_identity(provider) != trust:
            raise cases.CaseConflict("composite_choice_identity_changed")


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


def _prepare(case, subject_id, provider, selection_mode=None):
    # The canonical current-answer check includes current CITE rights. Every
    # bound plan, export and outcome reuses this path under the same case lock.
    decision, answer, base = legacy._current(case)
    legacy._approver(decision, cases._identity(provider, subject_id, case), provider)
    manifest = media.manifest_for_locked_answer(answer)
    if manifest is None:
        raise cases.CaseConflict("composite_manifest_required")
    existing = CompositeDelivery.objects.filter(decision=decision).first()
    if selection_mode is None:
        selection_mode = existing.selection_mode if existing else "ALL"
    if selection_mode not in {"ALL", "TEXT_ONLY"}:
        raise cases.CaseConflict("composite_selection_invalid")
    if existing and existing.selection_mode != selection_mode:
        raise cases.CaseConflict("composite_selection_already_bound")
    if selection_mode == "TEXT_ONLY":
        if getattr(settings, "FATWA_COMPOSITE_CHOICES_ENABLED", False) is not True:
            raise cases.CaseConflict("composite_selection_disabled")
        selected = [part for part in manifest["parts"] if part["kind"] == "TEXT"]
        if (
            len(selected) != 1
            or selected[0]["ordinal"] != 1
            or not any(part["kind"] == "AUDIO" for part in manifest["parts"])
        ):
            raise cases.CaseConflict("text_only_requires_approved_text_and_audio")
        manifest = {
            **manifest,
            "parts": selected,
            "selection_mode": selection_mode,
            "omitted_parts": [part for part in manifest["parts"] if part["kind"] != "TEXT"],
            "_choice_identity_pin": _choice_identity(provider),
        }
    origin = cases._delivery_origin_for_locked_case(case)
    profile = _profile(origin["channel"])
    capability_sha = _profile_hash(profile)
    evidence = replace(
        base, answer_sha256=manifest["sha256"], source_digest=_hash([base.source_digest, origin])
    )
    parts = tuple(
        Part(
            p["ordinal"],
            {
                "TEXT": "text",
                "FILE": "document",
                "AUDIO": "audio",
                "IMAGE": "image",
                "YOUTUBE_LINK": "link",
            }[p["kind"]],
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
        if selection_mode == "TEXT_ONLY":
            # The explicit omission choice is signed alongside the complete
            # approved manifest; it cannot reuse approval for an all-part plan.
            key = _hash(
                [
                    "composite-selection.v1",
                    selection_mode,
                    manifest["sha256"],
                    manifest["omitted_parts"],
                    key,
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
        fresh = _prepare(case, subject_id, provider, prepared[1].get("selection_mode", "ALL"))
        if case_key != case.public_ref or fresh != prepared:
            raise cases.CaseConflict("composite_context_changed")
        return fresh[3]

    return read


@mutation_service
def prepare_composite_delivery(
    *, case_id, subject_id, provider, selection_mode=None, synthetic_fixtures_only=False
):
    """Read-only full plan; unsupported parts remain visible for human action."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = _prepare(case, subject_id, provider, selection_mode)
        decision, manifest, capability_sha, evidence, plan = prepared
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return {
            "status": "REQUEST_NOT_APPROVED",
            "origin_channel": cases._delivery_origin_for_locked_case(case)["channel"],
            "decision_id": str(decision.pk),
            "manifest_sha256": manifest["sha256"],
            "capability_sha256": capability_sha,
            "parts": manifest["parts"],
            "selection_mode": manifest.get("selection_mode", "ALL"),
            "omitted_parts": manifest.get("omitted_parts", []),
            "evidence": asdict(evidence),
            "plan": asdict(plan),
            "plan_sha256": canonical_plan_sha256(plan),
        }


@mutation_service
def stage_composite_delivery(
    *,
    case_id,
    subject_id,
    provider,
    receipt,
    verify_receipt,
    selection_mode=None,
    synthetic_fixtures_only=False,
):
    """Signed return approval stages all parts atomically in the existing queue."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = _prepare(case, subject_id, provider, selection_mode)
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
                selection_mode=manifest.get("selection_mode", "ALL"),
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


@mutation_service
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
        if lease is None:
            from . import retries

            if retries.present(binding):
                lease = retries.reserve_next(
                    case=case,
                    subject_id=subject_id,
                    provider=provider,
                    binding=binding,
                    worker_id=worker_id,
                    verify_worker=verify_worker,
                    verify_receipt=verify_receipt,
                )
        read(case.public_ref)
        return lease


@mutation_service
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
            )
            .first()
        )
        if intent is not None and intent.approval_id != binding.approval_id:
            from . import retries
            from .models import CompositeRetry

            if not CompositeRetry.objects.filter(
                delivery=binding, approval_id=intent.approval_id
            ).exists():
                raise queue.QueueConflict("active_composite_lease_required")

            return retries.resolve_locked(
                case=case,
                subject_id=subject_id,
                provider=provider,
                lease=lease,
                intent=intent,
                verify_receipt=verify_receipt,
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


@mutation_service
def record_composite_event(
    *, case_id, subject_id, provider, lease, event, verifier, synthetic_fixtures_only=False
):
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        if getattr(event, "plan_fingerprint", None) != binding.approval.plan_fingerprint:
            from . import retries

            return retries.record_locked(
                case=case,
                subject_id=subject_id,
                provider=provider,
                lease=lease,
                event=event,
                verifier=verifier,
            )
        result = record_signed_provider_event(lease=lease, event=event, verifier=verifier)
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return result


@mutation_service
def composite_status(*, case_id, subject_id, provider, verifier, synthetic_fixtures_only=False):
    """Staff projection: queue state and cryptographic delivery proof are separate."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        from . import retries

        if retries.enabled() or retries.present(binding):
            with retries.boundary(
                case_id=case_id,
                subject_id=subject_id,
                provider=provider,
                synthetic_fixtures_only=synthetic_fixtures_only,
            ):
                result = retries.status_locked(binding, verifier)
                _reader(case, subject_id, provider, prepared)(case.public_ref)
                return result
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


@mutation_service
def reconcile_composite_timeouts(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    """Explicit local reconciliation: quarantine elapsed leases, never resend."""
    _enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        binding, prepared = _bound(case, subject_id, provider)
        changed = queue.quarantine_expired_leases(
            plan_fingerprint=binding.approval.plan_fingerprint,
        )
        from . import retries

        if retries.present(binding):
            with retries.boundary(
                case_id=case_id,
                subject_id=subject_id,
                provider=provider,
                synthetic_fixtures_only=synthetic_fixtures_only,
            ):
                for chain in retries.chains(binding, retries._verifier()):
                    if chain["history"]:
                        changed += queue.quarantine_expired_leases(
                            plan_fingerprint=chain["leaf"].plan_fingerprint
                        )
        _reader(case, subject_id, provider, prepared)(case.public_ref)
        return {"unresolved_parts": len(changed), "automatic_retry": False}
