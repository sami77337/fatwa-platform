"""Non-destructive case lifecycle over canonical approval and delivery evidence."""

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.apps import apps
from django.conf import settings
from django.db import connection

from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import Case, CaseDelivery, CaseEvent
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
)
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .authority import LifecycleAuthority
from .models import LifecycleEvent

ZERO = "0" * 64
STATE_LABELS = {"OPEN": "متابعة جارية", "CLOSED": "مغلقة", "ARCHIVED": "مؤرشفة"}
ACTION_LABELS = {
    "CLOSE": "إغلاق القضية",
    "REOPEN": "إعادة فتح القضية",
    "ARCHIVE": "أرشفة القضية المغلقة",
    "RESTORE": "استعادة القضية من الأرشيف",
    "FOLLOWUP": "إعادة فتح بسبب تعقيب جديد",
}
TRANSITIONS = {
    ("OPEN", "CLOSE"): "CLOSED",
    ("CLOSED", "REOPEN"): "OPEN",
    ("CLOSED", "ARCHIVE"): "ARCHIVED",
    ("ARCHIVED", "RESTORE"): "CLOSED",
    ("CLOSED", "FOLLOWUP"): "OPEN",
    ("ARCHIVED", "FOLLOWUP"): "OPEN",
}
MAX_EVENTS = 4096


def enabled():
    return getattr(settings, "FATWA_CASE_LIFECYCLE_ENABLED", False) is True


def _enabled():
    if not enabled():
        raise cases.CaseConflict("case_lifecycle_disabled")


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def _identity_pin(actor):
    # A renewed expiry is allowed; resolve_identity independently checks freshness.
    return actor.subject_id, actor.role, actor.active, actor.case_keys, actor.auth_epoch


def _epoch(authority):
    if not isinstance(authority, LifecycleAuthority):
        raise cases.CaseConflict("lifecycle_authority_required")
    try:
        result = authority.projection_epoch()
    except Exception:
        raise cases.CaseConflict("lifecycle_policy_unavailable") from None
    if type(result) is not str or not 1 <= len(result) <= 128:
        raise cases.CaseConflict("lifecycle_policy_snapshot_required")
    return result


def _event_hash(event):
    return _digest(
        {
            key: getattr(event, key)
            for key in (
                "id",
                "case_id",
                "version",
                "action",
                "before_state",
                "state",
                "reason",
                "case_revision",
                "evidence_version",
                "answer_id",
                "actor_kind",
                "subject_id",
                "provider_id",
                "auth_epoch",
                "policy_epoch",
                "command_id",
                "command_sha256",
                "canonical_event_id",
                "context",
                "previous_sha256",
            )
        }
    )


def _history(case, *, pending_followup=False):
    rows = list(LifecycleEvent.objects.filter(case=case).order_by("version")[: MAX_EVENTS + 1])
    if len(rows) > MAX_EVENTS:
        raise cases.CaseConflict("lifecycle_history_limit")
    state, previous = "OPEN", ZERO
    for number, row in enumerate(rows, 1):
        if (
            row.version != number
            or row.before_state != state
            or TRANSITIONS.get((state, row.action)) != row.state
            or row.previous_sha256 != previous
            or row.sha256 != _event_hash(row)
            or row.case_revision > case.revision
            or row.evidence_version > case.evidence_version
        ):
            raise cases.CaseConflict("lifecycle_history_invalid")
        state, previous = row.state, row.sha256
    if (
        rows
        and state != "OPEN"
        and not pending_followup
        and (
            rows[-1].evidence_version != case.evidence_version
            or rows[-1].answer_id != case.approved_answer_id
        )
    ):
        raise cases.CaseConflict("lifecycle_canonical_reopen_missing")
    return rows, state


def _resource(case, rows=None, state=None):
    if rows is None:
        rows, state = _history(case)
    return {
        "case_id": str(case.pk),
        "case_revision": case.revision,
        "evidence_version": case.evidence_version,
        "answer_id": str(case.approved_answer_id) if case.approved_answer_id else None,
        "version": len(rows),
        "state": state,
        "sha256": rows[-1].sha256 if rows else ZERO,
    }


def _snapshot(locked):
    ids = [case.pk for case in locked]
    refs = [case.public_ref for case in locked]
    claims = ApprovalClaim.objects.filter(case_key__in=refs)
    intents = DeliveryIntent.objects.filter(approval__in=claims)
    return _digest(
        [
            list(Case.objects.filter(pk__in=ids).order_by("pk").values()),
            list(
                LifecycleEvent.objects.filter(case_id__in=ids)
                .order_by("case_id", "version")
                .values()
            ),
            list(claims.order_by("pk").values()),
            list(intents.order_by("pk").values()),
            list(ProviderReceipt.objects.filter(intent__in=intents).order_by("pk").values()),
            list(
                ProviderSignatureEvidence.objects.filter(receipt__intent__in=intents)
                .order_by("pk")
                .values()
            ),
            list(CaseDelivery.objects.filter(decision__case_id__in=ids).order_by("pk").values()),
            (
                list(
                    apps.get_model("composite_delivery", "CompositeDelivery")
                    .objects.filter(decision__case_id__in=ids)
                    .order_by("pk")
                    .values()
                )
                if apps.is_installed("apps.composite_delivery")
                else []
            ),
            (
                list(
                    apps.get_model("composite_delivery", "CompositeRetry")
                    .objects.filter(delivery__decision__case_id__in=ids)
                    .order_by("pk")
                    .values()
                )
                if apps.is_installed("apps.composite_delivery")
                else []
            ),
            getattr(settings, "FATWA_COMPOSITE_RETRY_ENABLED", False) is True,
        ]
    )


@dataclass
class ProjectionGuard:
    locked: list
    actor: object
    provider: object
    authority: object
    directory: object
    verifier: object
    composite_verifier: object
    epoch: str
    provider_id: str
    watermark: str
    permissions: list = field(default_factory=list)
    identities: dict = field(default_factory=dict)

    def permit(self, case, action, resource=None, *, required=True):
        resource = resource or _resource(case)
        arguments = dict(
            provider_id=self.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            resource=resource,
        )
        try:
            allowed = self.authority.permits(**{**arguments, "resource": dict(resource)}) is True
        except Exception:
            raise cases.CaseConflict("lifecycle_policy_unavailable") from None
        self.permissions.append((arguments, allowed))
        if required and not allowed:
            raise cases.CaseConflict("lifecycle_permission_denied")
        return allowed

    def freeze(self):
        """Only after an intentional command, before any new projection callbacks."""
        self.watermark = _snapshot(self.locked)

    def check(self):
        _enabled()
        if (
            getattr(settings, "FATWA_CASE_LIFECYCLE_AUTHORITY", None) is not self.authority
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None) is not self.verifier
            or getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
            is not self.composite_verifier
            or self.provider.provider_id != self.provider_id
            or _epoch(self.authority) != self.epoch
        ):
            raise cases.CaseConflict("lifecycle_configuration_changed")
        # Run callbacks first; pure snapshots/epoch checks run after the last one.
        for arguments, expected in self.permissions:
            try:
                current = (
                    self.authority.permits(**{**arguments, "resource": dict(arguments["resource"])})
                    is True
                )
            except Exception:
                raise cases.CaseConflict("lifecycle_policy_unavailable") from None
            if current != expected:
                raise cases.CaseConflict("lifecycle_permission_changed")
        for subject, (provider, expected) in self.identities.items():
            try:
                current = resolve_identity(provider, subject)
            except IdentityUnavailable:
                raise cases.CaseConflict("lifecycle_approval_changed") from None
            if _identity_pin(current) != expected:
                raise cases.CaseConflict("lifecycle_approval_changed")
        try:
            actor = resolve_identity(self.provider, self.actor.subject_id)
        except IdentityUnavailable:
            raise cases.CaseConflict("lifecycle_identity_changed") from None
        if _identity_pin(actor) != _identity_pin(self.actor):
            raise cases.CaseConflict("lifecycle_identity_changed")
        if (
            not enabled()
            or getattr(settings, "FATWA_CASE_LIFECYCLE_AUTHORITY", None) is not self.authority
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None) is not self.verifier
            or getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
            is not self.composite_verifier
            or self.provider.provider_id != self.provider_id
            or _epoch(self.authority) != self.epoch
            or _snapshot(self.locked) != self.watermark
        ):
            raise cases.CaseConflict("lifecycle_projection_changed")


@contextmanager
def projection_boundary(*, subject_id, provider, synthetic_fixtures_only=False, case_ids=None):
    """Locks and pre-read pins cover all row callbacks and the caller's render."""
    _enabled()
    cases._guard(synthetic_fixtures_only)
    authority = getattr(settings, "FATWA_CASE_LIFECYCLE_AUTHORITY", None)
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    verifier = getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None)
    composite_verifier = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
    epoch = _epoch(authority)
    try:
        actor = resolve_identity(provider, subject_id)
    except IdentityUnavailable:
        raise cases.CaseConflict("lifecycle_identity_unavailable") from None
    identifiers = None if case_ids is None else {cases._uuid(value) for value in case_ids}
    with synthetic_queue_atomic():
        query = Case.objects.filter(public_ref__in=actor.case_keys)
        if identifiers is not None:
            query = query.filter(pk__in=identifiers)
        locked = list(query.order_by("pk").select_for_update())
        if identifiers is not None and len(locked) != len(identifiers):
            raise cases.CaseConflict("lifecycle_case_unavailable")
        for case in locked:
            cases._verify(case)
            _history(case)
        guard = ProjectionGuard(
            locked=locked,
            actor=actor,
            provider=provider,
            authority=authority,
            directory=directory,
            verifier=verifier,
            composite_verifier=composite_verifier,
            epoch=epoch,
            provider_id=provider.provider_id,
            watermark=_snapshot(locked),
        )
        yield guard
        guard.check()


def _closure(case, guard, *, without_delivery=False):
    decision, answer, _ = delivery._current(case)
    # The recorded scholarly approver must still be a current scoped MUFTI.
    approver = cases._identity(guard.directory, decision.subject_id, case)
    if decision.provider_id != guard.provider_id or decision.auth_epoch != approver.auth_epoch:
        raise cases.CaseConflict("lifecycle_approval_changed")
    guard.identities[approver.subject_id] = (guard.directory, _identity_pin(approver))
    claims = list(ApprovalClaim.objects.filter(case_key=case.public_ref).order_by("pk"))
    proofs = []
    current = []
    resolved_retry_plans = set()
    for claim in claims:
        legacy = (
            CaseDelivery.objects.filter(approval=claim).select_related("decision__answer").first()
        )
        composite = None
        retry = None
        if apps.is_installed("apps.composite_delivery"):
            composite = (
                apps.get_model("composite_delivery", "CompositeDelivery")
                .objects.filter(approval=claim)
                .select_related("decision__answer")
                .first()
            )
            retry = (
                apps.get_model("composite_delivery", "CompositeRetry")
                .objects.filter(approval=claim)
                .select_related("delivery__decision__answer", "delivery__approval")
                .first()
            )
            if retry is not None:
                if composite is not None:
                    raise cases.CaseConflict("lifecycle_delivery_binding_invalid")
                composite = retry.delivery
        binding = legacy or composite
        if (
            binding is None
            or (legacy is not None and composite is not None)
            or binding.decision.case_id != case.pk
            or binding.decision.answer.revision != claim.answer_revision
            or (claim.answer_revision == answer.revision and binding.decision_id != decision.pk)
        ):
            raise cases.CaseConflict("lifecycle_delivery_binding_invalid")
        if composite is not None:
            from apps.composite_delivery import retries

            if retries.present(composite):
                if claim.plan_fingerprint in resolved_retry_plans:
                    continue
                try:
                    result = retries.status_locked(composite, guard.composite_verifier)
                except Exception:
                    raise cases.CaseConflict("lifecycle_delivery_unresolved") from None
                if not result["delivery_verified"]:
                    raise cases.CaseConflict("lifecycle_delivery_unresolved")
                # Only this exact validated ancestry may reconcile its preserved
                # failed claims. Other historical or unbound claims still pass
                # through the original conservative checks below.
                resolved_retry_plans.update(result["retained_plans"])
                proofs.append(
                    {
                        "plan": composite.approval.plan_fingerprint,
                        "parts": result["expected_parts"],
                        "original_state": result["original_plan"]["state"],
                        "retry_plans": result["retained_plans"],
                    }
                )
                if claim.answer_revision == answer.revision:
                    current.append(claim)
                continue
        try:
            evidence = audit_provider_reported_delivery(
                plan_fingerprint=claim.plan_fingerprint,
                verifier=guard.verifier if legacy is not None else guard.composite_verifier,
            )
        except Exception:
            raise cases.CaseConflict("lifecycle_delivery_unresolved") from None
        if not evidence.cryptographically_verified_complete:
            raise cases.CaseConflict("lifecycle_delivery_unresolved")
        proofs.append({"plan": claim.plan_fingerprint, "parts": evidence.expected_parts})
        if claim.answer_revision == answer.revision:
            current.append(claim)
    if not current:
        if claims:
            # A prior plan cannot prove the current answer reached its recipient.
            raise cases.CaseConflict("lifecycle_current_answer_delivery_missing")
        if without_delivery is not True:
            raise cases.CaseConflict("lifecycle_explicit_no_delivery_choice_required")
        guard.permit(case, "CLOSE_WITHOUT_DELIVERY")
    elif without_delivery:
        raise cases.CaseConflict("lifecycle_no_delivery_choice_inapplicable")
    return {
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "answer_sha256": answer.text_sha256,
        "decision_id": str(decision.pk),
        "delivery": "SIGNED_COMPLETE" if current else "NO_DELIVERY_CLAIM",
        "plans": proofs,
        "read_confirmed": False,
    }


def _row(case, guard, *, include_history=False, controls=False):
    rows, state = _history(case)
    resource = _resource(case, rows, state)
    if not guard.permit(case, "READ", resource, required=False):
        return None
    result = {
        "case_id": str(case.pk),
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "version": len(rows),
        "state": state,
        "state_label": STATE_LABELS[state],
        "approved_answer_id": resource["answer_id"],
        "last_reason": rows[-1].reason if rows else "",
        "updated_at": rows[-1].created_at if rows else case.created_at,
        "actions": [],
        "close_blocked": "",
    }
    if include_history:
        result["history"] = [
            {
                "version": row.version,
                "action": row.action,
                "label": ACTION_LABELS[row.action],
                "state_label": STATE_LABELS[row.state],
                "reason": row.reason,
                "created_at": row.created_at,
                "actor": "تعقيب المستفتي"
                if row.actor_kind == "REQUESTER_EVENT"
                else row.subject_id,
                "case_revision": row.case_revision,
                "evidence_version": row.evidence_version,
                "no_delivery_claim": row.context.get("delivery") == "NO_DELIVERY_CLAIM",
            }
            for row in reversed(rows)
        ]
    if controls:
        for action in ("CLOSE", "REOPEN", "ARCHIVE", "RESTORE"):
            if (state, action) not in TRANSITIONS or not guard.permit(
                case, action, resource, required=False
            ):
                continue
            without_delivery = False
            if action == "CLOSE":
                without_delivery = not ApprovalClaim.objects.filter(
                    case_key=case.public_ref
                ).exists()
                try:
                    _closure(case, guard, without_delivery=without_delivery)
                except cases.CaseConflict:
                    result["close_blocked"] = (
                        "الإغلاق غير متاح: يلزم جواب معتمد حالي، وحسم التوصيل، أو إذن مستقل "
                        "واختيار صريح للإغلاق دون ادعاء توصيل عند عدم وجود خطة."
                    )
                    continue
            result["actions"].append(
                {
                    "action": action,
                    "form_action": "lc_" + action.lower(),
                    "label": ACTION_LABELS[action],
                    "without_delivery": without_delivery,
                }
            )
    return result


@mutation_service
def desk(*, case_id, **common):
    with projection_boundary(**common, case_ids=[case_id]) as guard:
        result = _row(guard.locked[0], guard, include_history=True, controls=True)
        if result is None:
            raise cases.CaseConflict("lifecycle_permission_denied")
        result["_guard"] = guard
        return result


@mutation_service
def inbox(*, state="ARCHIVED", query="", **common):
    if state not in {*STATE_LABELS, "ALL"} or type(query) is not str or len(query) > 128:
        raise cases.CaseConflict("lifecycle_filter_invalid")
    with projection_boundary(**common) as guard:
        visible = [row for case in guard.locked if (row := _row(case, guard)) is not None]
        counts = {key: sum(row["state"] == key for row in visible) for key in STATE_LABELS}
        query = query.strip()
        rows = [
            row
            for row in visible
            if (state == "ALL" or row["state"] == state)
            and (
                not query
                or query.casefold() in (row["public_ref"] + " " + row["last_reason"]).casefold()
            )
        ]
        rows.sort(key=lambda row: (row["updated_at"], row["public_ref"]), reverse=True)
        return {
            "rows": rows,
            "counts": counts,
            "count": len(rows),
            "state": state,
            "query": query,
            "_guard": guard,
        }


@contextmanager
def queue_projection(rows, *, states=("OPEN",), **common):
    """Use around final queue/search rendering; filter before computing counts.

    Input rows must be existing canonical staff DTOs. A read made before these
    locks is usable only if its exact case/evidence/revision still matches.
    Disabled features preserve the prior queue; enabling without authority denies.
    """
    if not enabled():
        yield rows
        return
    if not set(states) <= set(STATE_LABELS):
        raise cases.CaseConflict("lifecycle_filter_invalid")
    with projection_boundary(**common, case_ids=[row["case_id"] for row in rows]) as guard:
        sources = {str(case.pk): case for case in guard.locked}
        visible = []
        for row in rows:
            case = sources[row["case_id"]]
            if (row["public_ref"], row["revision"], row["evidence_version"]) != (
                case.public_ref,
                case.revision,
                case.evidence_version,
            ):
                raise cases.CaseConflict("lifecycle_queue_source_changed")
            projected = _row(case, guard)
            if projected is not None and projected["state"] in states:
                visible.append({**row, "lifecycle": projected})
        yield visible


def _reason(value):
    if type(value) is not str or not 1 <= len(value) <= 1000 or not value.strip():
        raise cases.CaseConflict("lifecycle_reason_required")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise cases.CaseConflict("lifecycle_reason_invalid") from None
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise cases.CaseConflict("lifecycle_reason_invalid")
    return value


def _append(
    case,
    rows,
    state,
    *,
    action,
    reason,
    actor_kind,
    subject_id,
    provider_id,
    auth_epoch,
    policy_epoch,
    command_id,
    command_sha256,
    context,
    canonical_event=None,
):
    target = TRANSITIONS.get((state, action))
    if target is None or len(rows) >= MAX_EVENTS:
        raise cases.CaseConflict("lifecycle_transition_unavailable")
    event = LifecycleEvent(
        case=case,
        version=len(rows) + 1,
        action=action,
        before_state=state,
        state=target,
        reason=reason,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        answer_id=case.approved_answer_id,
        actor_kind=actor_kind,
        subject_id=subject_id,
        provider_id=provider_id,
        auth_epoch=auth_epoch,
        policy_epoch=policy_epoch,
        command_id=command_id,
        command_sha256=command_sha256,
        canonical_event=canonical_event,
        context=context,
        previous_sha256=rows[-1].sha256 if rows else ZERO,
    )
    event.sha256 = _event_hash(event)
    event.save(force_insert=True)
    return event


@mutation_service
def command(
    *,
    case_id,
    action,
    reason,
    expected_revision,
    expected_evidence_version,
    expected_version,
    command_id,
    without_delivery=False,
    **common,
):
    if (
        action not in {"CLOSE", "REOPEN", "ARCHIVE", "RESTORE"}
        or type(without_delivery) is not bool
    ):
        raise cases.CaseConflict("lifecycle_action_invalid")
    if type(expected_version) is not int or not 0 <= expected_version < MAX_EVENTS:
        raise cases.CaseConflict("lifecycle_version_invalid")
    if without_delivery and action != "CLOSE":
        raise cases.CaseConflict("lifecycle_no_delivery_choice_inapplicable")
    reason, command_id = _reason(reason), cases._uuid(command_id)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    command_sha = _digest(
        [
            str(case_id),
            action,
            reason,
            expected_revision,
            expected_evidence_version,
            expected_version,
            without_delivery,
        ]
    )
    with projection_boundary(**common, case_ids=[case_id]) as guard:
        case = guard.locked[0]
        rows, state = _history(case)
        guard.permit(case, "READ")
        guard.permit(case, action)
        previous = next(
            (
                row
                for row in rows
                if row.command_id == command_id
                and row.provider_id == guard.provider_id
                and row.subject_id == guard.actor.subject_id
            ),
            None,
        )
        if previous is not None:
            if previous.command_sha256 != command_sha:
                raise cases.CaseConflict("lifecycle_command_conflict")
            if without_delivery:
                guard.permit(case, "CLOSE_WITHOUT_DELIVERY")
            return {
                "version": previous.version,
                "state": previous.state,
                "event_id": str(previous.pk),
                "replayed": True,
            }
        cases._versions(case, expected_revision, expected_evidence_version)
        if len(rows) != expected_version:
            raise cases.CaseConflict("lifecycle_version_changed")
        if (state, action) not in TRANSITIONS:
            raise cases.CaseConflict("lifecycle_transition_unavailable")
        context = {"delivery": "UNCHANGED", "read_confirmed": False}
        if action == "CLOSE":
            context = _closure(case, guard, without_delivery=without_delivery)
        guard.check()  # No callback can mutate the precondition baseline unnoticed.
        event = _append(
            case,
            rows,
            state,
            action=action,
            reason=reason,
            actor_kind="STAFF",
            subject_id=guard.actor.subject_id,
            provider_id=guard.provider_id,
            auth_epoch=guard.actor.auth_epoch,
            policy_epoch=guard.epoch,
            command_id=command_id,
            command_sha256=command_sha,
            context=context,
        )
        guard.freeze()  # Intentional own write; no DTO was read before this baseline.
        return {
            "version": event.version,
            "state": event.state,
            "event_id": str(event.pk),
            "replayed": False,
        }


def before_canonical_event(*, case, action):
    """Require explicit reopening before new staff work, inside the core unit.

    Call before `_event` saves Case. Canonical services may already have created
    a draft inside their atomic transaction; denial rolls that whole unit back.
    Access revocation/rotation is unaffected. Requester facts use record_followup.
    """
    if not enabled() or action not in {
        "SAVE_ANSWER",
        "CLARIFICATION",
        "APPROVE",
        "RETURN_FOR_CHANGES",
    }:
        return
    if not connection.in_atomic_block:
        raise cases.CaseConflict("lifecycle_event_transaction_required")
    current = Case.objects.select_for_update().get(pk=case.pk)
    _, state = _history(current)
    if state != "OPEN":
        raise cases.CaseConflict("lifecycle_reopen_before_staff_work")


def record_followup(*, case, event):
    """Atomic canonical FOLLOWUP effect, never a callable HTTP principal.

    The integrator calls this immediately after CaseEvent creation inside _event.
    Both text followups and accepted requester attachments already use that hook.
    Canonical capability validation remains the caller's existing responsibility;
    this helper independently verifies the exact committed event/case relationship.
    """
    if not enabled():
        return None
    if not connection.in_atomic_block:
        raise cases.CaseConflict("lifecycle_followup_transaction_required")
    current = Case.objects.select_for_update().get(pk=case.pk)
    saved = CaseEvent.objects.filter(pk=event.pk, case=current).first()
    if (
        saved is None
        or saved.action != "FOLLOWUP"
        or saved.subject_id != current.requester_id
        or saved.sequence != current.revision
        or saved.evidence_version != current.evidence_version
        or current.stage != "UNDER_REVIEW"
        or current.approved_answer_id is not None
    ):
        raise cases.CaseConflict("lifecycle_followup_event_invalid")
    cases._verify(current)
    rows, state = _history(current, pending_followup=True)
    repeated = next((row for row in rows if row.canonical_event_id == saved.pk), None)
    if repeated is not None:
        return {"version": repeated.version, "state": repeated.state}
    if state == "OPEN":
        return None
    command_id = uuid.uuid5(uuid.NAMESPACE_URL, "fatwa-lifecycle-followup:" + str(saved.pk))
    result = _append(
        current,
        rows,
        state,
        action="FOLLOWUP",
        reason="وصل تعقيب جديد إلى القضية نفسها.",
        actor_kind="REQUESTER_EVENT",
        subject_id=current.requester_id,
        provider_id="casework-followup",
        auth_epoch="canonical-event",
        policy_epoch="canonical-event",
        command_id=command_id,
        command_sha256=_digest([str(current.pk), saved.pk]),
        context={"canonical_event": saved.pk, "delivery": "UNCHANGED", "read_confirmed": False},
        canonical_event=saved,
    )
    return {"version": result.version, "state": result.state}
