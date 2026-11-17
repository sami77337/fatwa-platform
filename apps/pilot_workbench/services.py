"""Native local fixture actions over canonical case + existing composite queue only."""

import os
from hmac import compare_digest

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import delivery as legacy
from apps.casework import services as cases
from apps.composite_delivery import desk as control
from apps.composite_delivery import services as composite
from apps.composite_delivery.models import CompositeDelivery
from apps.delivery_queue import approval_adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent

from .fixtures import MAX_LEASES, PilotFixture


def _fixture(ack):
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PILOT_WORKBENCH_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("pilot_workbench_disabled")
    cases._guard(ack)
    fixture = getattr(settings, "FATWA_PILOT_WORKBENCH", None)
    if not isinstance(fixture, PilotFixture) or timezone.now() >= fixture.expires_at:
        raise cases.CaseConflict("pilot_fixture_unavailable")
    if (
        getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not fixture.identity_provider
        or getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None)
        is not fixture.approval_verifier
        or getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
        is not fixture.provider_verifier
        or fixture.provider_fixture.verifier is not fixture.provider_verifier
    ):
        raise cases.CaseConflict("pilot_fixture_profile_changed")
    if connection.in_atomic_block:
        raise cases.CaseConflict("pilot_outer_transaction_unsupported")
    return fixture


def _operator(fixture, case, subject_id, provider, action):
    actor = cases._identity(provider, subject_id, case)
    trusted = cases._identity(fixture.identity_provider, subject_id, case)
    if actor != trusted or provider.provider_id != fixture.identity_provider.provider_id:
        raise cases.CaseConflict("pilot_identity_changed")
    try:
        allowed = fixture.operator_authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("pilot_operator_denied") from exc
    if allowed is not True or timezone.now() >= fixture.expires_at:
        raise cases.CaseConflict("pilot_operator_denied")
    return actor


def _profile_still_current(fixture):
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PILOT_WORKBENCH", None) is not fixture
        or getattr(settings, "FATWA_PILOT_WORKBENCH_ENABLED", False) is not True
        or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        is not fixture.identity_provider
        or getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None)
        is not fixture.approval_verifier
        or getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
        is not fixture.provider_verifier
        or fixture.provider_fixture.verifier is not fixture.provider_verifier
    ):
        raise cases.CaseConflict("pilot_fixture_profile_changed")


def read_workbench(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    fixture = _fixture(synthetic_fixtures_only)
    with (
        fixture.lock,
        legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _),
    ):
        actor = _operator(fixture, case, subject_id, provider, "OPEN")
        result = control.read_delivery_desk(
            case_id=case.pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
        )
        fingerprint = result.get("plan_sha256", "")
        first = next((p["id"] for p in result["parts"] if p["state"] == "STAGED"), None)
        for part in result["parts"]:
            cache = fixture._attempts.get((fingerprint, part["id"]))
            options = []
            if result.get("permission_valid") and part["supported"]:
                if part["state"] == "STAGED" and part["id"] == first:
                    options = ["ACCEPTED", "DELIVERED", "FAILED"]
                elif cache and part["state"] in {"LEASED", "UNKNOWN_REQUIRES_RECONCILIATION"}:
                    options = ["ACCEPTED", "DELIVERED", "FAILED"]
                elif cache and part["state"] == "SENT_UNCONFIRMED":
                    options = ["DELIVERED", "FAILED"]
            part["pilot_outcomes"] = options
            part["pilot_memory_missing"] = bool(
                part["attempted"]
                and not cache
                and part["state"] not in {"DELIVERED", "FAILED_REQUIRES_REVIEW"}
            )
        if actor != _operator(fixture, case, subject_id, provider, "OPEN"):
            raise cases.CaseConflict("pilot_identity_changed")
        _profile_still_current(fixture)
        return result


def apply_action(
    *,
    case_id,
    subject_id,
    provider,
    action,
    revision,
    evidence_version,
    plan_sha256,
    confirmed=False,
    part_id="",
    expected_state="",
    outcome="",
    synthetic_fixtures_only=False,
):
    fixture = _fixture(synthetic_fixtures_only)
    if confirmed is not True or action not in {"pilot_authorize", "pilot_report"}:
        raise cases.CaseConflict("pilot_explicit_confirmation_required")
    receipt_id = None
    with fixture.lock:
        pending = dict(fixture._attempts)
        try:
            with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
                case,
                _,
            ):
                permission = (
                    "AUTHORIZE_RETURN" if action == "pilot_authorize" else "REPORT_PROVIDER"
                )
                actor = _operator(fixture, case, subject_id, provider, permission)
                cases._versions(case, revision, evidence_version)
                common = dict(
                    case_id=case.pk,
                    subject_id=subject_id,
                    provider=provider,
                    synthetic_fixtures_only=True,
                )
                prepared = composite.prepare_composite_delivery(**common)
                if not queue._hex(plan_sha256) or not compare_digest(
                    plan_sha256, prepared["plan_sha256"]
                ):
                    raise cases.CaseConflict("pilot_plan_changed")
                if prepared["plan"]["status"] != "PLANNED_NOT_SENT":
                    raise cases.CaseConflict("pilot_unsupported_capability")
                if action == "pilot_authorize":
                    if part_id or expected_state or outcome:
                        raise cases.CaseConflict("pilot_permission_fields_invalid")
                    if CompositeDelivery.objects.filter(
                        decision_id=prepared["decision_id"]
                    ).exists():
                        raise cases.CaseConflict("pilot_permission_already_recorded")
                    receipt = fixture._return_authority._issue_locked(
                        prepared, actor, provider.provider_id
                    )
                    receipt_id = receipt.receipt_id
                    composite.stage_composite_delivery(
                        **common, receipt=receipt, verify_receipt=fixture.approval_verifier
                    )
                    notice = "سُجل إذن الإرجاع التجريبي المنفصل لكل الأجزاء. لم يحدث إرسال."
                else:
                    if outcome not in {"ACCEPTED", "DELIVERED", "FAILED"}:
                        raise cases.CaseConflict("pilot_outcome_invalid")
                    part = next((p for p in prepared["parts"] if p["id"] == part_id), None)
                    binding = CompositeDelivery.objects.filter(
                        decision_id=prepared["decision_id"]
                    ).first()
                    if part is None or binding is None:
                        raise cases.CaseConflict("pilot_part_unavailable")
                    rows = list(
                        DeliveryIntent.objects.filter(approval=binding.approval).order_by("ordinal")
                    )
                    row = next((r for r in rows if r.ordinal == part["ordinal"]), None)
                    if row is None or row.state != expected_state:
                        raise cases.CaseConflict("pilot_part_state_changed")
                    key = (plan_sha256, part_id)
                    cached = pending.get(key)
                    if row.state == "STAGED":
                        first = next((r for r in rows if r.state == "STAGED"), None)
                        if first != row or cached or len(pending) >= MAX_LEASES:
                            raise cases.CaseConflict("pilot_next_part_required")
                        lease = composite.reserve_composite_part(
                            **common,
                            worker_id=fixture.worker_id,
                            verify_worker=lambda worker, plan: (
                                worker == fixture.worker_id and plan == plan_sha256
                            ),
                            verify_receipt=fixture.approval_verifier,
                        )
                        if lease is None or lease.intent_key != row.pk:
                            raise cases.CaseConflict("pilot_part_changed")
                        resolved = composite.resolve_composite_part(
                            **common, lease=lease, verify_receipt=fixture.approval_verifier
                        )
                    else:
                        if cached is None or row.state not in {
                            "LEASED",
                            "SENT_UNCONFIRMED",
                            "UNKNOWN_REQUIRES_RECONCILIATION",
                        }:
                            raise cases.CaseConflict("pilot_existing_attempt_required")
                        if row.state == "SENT_UNCONFIRMED" and outcome == "ACCEPTED":
                            raise cases.CaseConflict("pilot_part_state_changed")
                        lease, resolved = cached
                    # Reverify current independent return permission, including revocation/expiry.
                    approval_adapter._verify_current_claim(
                        binding.approval,
                        fixture.approval_verifier,
                        lambda _: composite._prepare(case, subject_id, provider)[3],
                    )
                    event = fixture.provider_fixture.event(
                        lease=lease, part=resolved, reported=outcome
                    )
                    composite.record_composite_event(
                        **common, lease=lease, event=event, verifier=fixture.provider_verifier
                    )
                    if outcome == "ACCEPTED":
                        pending[key] = (lease, resolved)
                    else:
                        pending.pop(key, None)
                    notice = (
                        "سُجل تقرير المحاكي المحلي للجزء المحدد. لا إرسال خارجي ولا إثبات قراءة."
                    )
                if composite.prepare_composite_delivery(**common)["plan_sha256"] != plan_sha256:
                    raise cases.CaseConflict("pilot_plan_changed")
                if actor != _operator(fixture, case, subject_id, provider, permission):
                    raise cases.CaseConflict("pilot_identity_changed")
                binding_now, current_plan = composite._bound(case, subject_id, provider)
                approval_adapter._verify_current_claim(
                    binding_now.approval,
                    fixture.approval_verifier,
                    composite._reader(case, subject_id, provider, current_plan),
                )
                _profile_still_current(fixture)
            # Only publish/remove worker memory after the outer database transaction commits.
            fixture._attempts = pending
            return notice
        except BaseException:
            if receipt_id:
                fixture._return_authority._issued.pop(receipt_id, None)
            raise
