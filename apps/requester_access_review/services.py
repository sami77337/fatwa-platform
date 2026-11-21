"""Use the existing core locks, capability checks and trusted scoped identities.

No function here issues, rotates, revokes, delivers, or restores a capability.
Private core context managers are intentionally reused at the pinned V6 boundary.
"""

from hashlib import sha256

from django.apps import apps as django_apps
from django.conf import settings
from django.utils import timezone

from apps.casework import delivery
from apps.casework import services as cases
from apps.delivery_queue.models import RequesterTrackingToken
from apps.delivery_queue.services import QueueConflict
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .models import AccessReview

REASONS = {"LOST_COPY": "فقدت نسختي من الرمز والوصول الحالي ما زال مفتوحًا",
           "EXPOSED": "أخشى أن رمز الوصول انكشف لشخص آخر"}
STATES = {"REQUESTED": "طلب المراجعة محفوظ",
          "VERIFYING": "الفريق يتابع التحقق الموثوق",
          "CLOSED": "أُغلق الطلب بعد إبطال الرمز السابق"}


def _public(review):
    return {"reason_label": REASONS[review.reason], "state_label": STATES[review.state],
            "created_at": review.created_at, "closed": review.state == "CLOSED"}


def _verify_binding(review, case):
    if review.case_id != case.pk or review.grant.case_id != case.tracking_id:
        raise cases.CaseConflict("access_review_binding_invalid")
    if review.state == "CLOSED" and review.grant.revoked_at is None:
        raise cases.CaseConflict("access_review_resolution_invalid")


def _requester_history(case, private_answer):
    """Allowlisted conversation projection, never the internal event/audit log.

    FOLLOWUP is also used by staff imports. Only an unannotated event authored
    by this requester represents their own submitted text. Imported evidence and
    attachment provenance have their own guarded surfaces and stay out of this one.
    """
    evidence = {item.version: item for item in case.evidence.all()}
    history = []
    for event in case.events.order_by("sequence"):
        kind, label, text = None, "", ""
        if event.action == "INTAKE":
            kind, label, text = "question", "سؤالك الأصلي كما وصل", evidence[1].text
        elif (
            event.action == "FOLLOWUP" and event.subject_id == case.requester_id and not event.note
        ):
            kind, label, text = "followup", "تعقيبك المحفوظ", evidence[event.evidence_version].text
        elif event.action == "CLARIFICATION":
            kind, label, text = "clarification", "استيضاح من الفريق", event.note
        elif (
            event.action == "APPROVE"
            and private_answer is not None
            and event.answer_id == case.approved_answer_id
        ):
            kind, label = "answer", "إصدار الجواب المعتمد المتاح حاليًا"
        if kind:
            history.append(
                {
                    "kind": kind,
                    "label": label,
                    "text": text,
                    "evidence_version": event.evidence_version,
                    "answer_revision": private_answer["revision"] if kind == "answer" else None,
                    "created_at": event.created_at,
                }
            )
    return history


@mutation_service
def requester_snapshot(
    token, *, verifier=None, show_approved_answer=False, synthetic_fixtures_only=False
):
    """Read private case, access reviews and signed proof under one locked snapshot.

    A text-only answer can be shown only when the server explicitly enables this
    private view AND all current delivery parts have verified signed evidence.
    A scholarly decision or an ACCEPTED callback alone never unlocks content.
    """
    with delivery._token_case(token, synthetic_fixtures_only) as case:
        result = delivery._requester_delivery_locked(case, verifier)
        private_answer = None
        if show_approved_answer is True and result["delivery_verified"] is True:
            # _bound checks that this exact immutable current answer, decision and
            # evidence match the separately signed return plan.
            decision, _, _ = delivery._bound(case)
            answer = case.approved_answer
            if answer is None or answer.pk != decision.answer_id:
                raise cases.CaseConflict("current_private_answer_unavailable")
            from apps.data_privacy.integration import allowed

            if allowed("ANSWER", answer.pk):
                private_answer = {"text": answer.text, "revision": answer.revision}
        private_media = {"available": False, "answer_revision": None, "part_count": None}
        if django_apps.is_installed("apps.answer_media"):
            from apps.answer_media.services import private_availability_for_locked_case

            private_media = private_availability_for_locked_case(case)
        reviews = list(AccessReview.objects.filter(case=case).select_related("grant")
                       .order_by("-created_at")[:10])
        for review in reviews:
            _verify_binding(review, case)
        return {
            "case": result,
            "reviews": [_public(review) for review in reviews],
            "private_answer": private_answer,
            "private_media_availability": private_media,
            "composite_delivery": _composite_delivery_locked(case, private_media),
            "requester_history": _requester_history(case, private_answer),
        }


def _composite_delivery_locked(case, availability):
    """Allowlisted signed multipart summary; never unlocks the legacy text path.

    The caller holds the token-authorized case lock and owned queue transaction.
    Explicit current portal availability is required before revealing this summary.
    Reuse the composite service's fresh actor, origin, capabilities and exact-plan
    checks; no part identifiers, source IDs or internal audit records cross here.
    """
    if (
        availability["available"] is not True
        or not django_apps.is_installed("apps.composite_delivery")
        or getattr(settings, "FATWA_COMPOSITE_DELIVERY_ENABLED", False) is not True
    ):
        return None
    verifier = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
    if not isinstance(verifier, Ed25519ProviderEventVerifier):
        return None
    from apps.casework_web.access import RequestDirectory
    from apps.composite_delivery.services import composite_status

    try:
        decision = case.approved_answer.decision
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        actor = cases._identity(directory, decision.subject_id, case)
        if (directory.provider_id, actor.auth_epoch) != (
            decision.provider_id, decision.auth_epoch
        ):
            return None
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=decision.provider_id
        )
        result = composite_status(
            case_id=str(case.pk), subject_id=actor.subject_id, provider=provider,
            verifier=verifier, synthetic_fixtures_only=True,
        )
        expected = result["expected_parts"]
        if expected != availability["part_count"] or not 2 <= expected <= 8:
            return None
        parts = result["parts"]
        if len(parts) != expected:
            return None
        return {
            "state": result["state"],
            "expected_parts": expected,
            "verified_parts": result["verified_parts"],
            "accepted_parts": sum(p["state"] == "SENT_UNCONFIRMED" for p in parts),
            "failed_parts": sum(p["state"] == "FAILED_REQUIRES_REVIEW" for p in parts),
            "unresolved_parts": sum(p["state"] == "UNKNOWN_REQUIRES_RECONCILIATION" for p in parts),
            "delivery_verified": result["delivery_verified"] is True
            and result["verified_parts"] == expected,
            "read_confirmed": False,
            "human_action": result["human_action"] is True,
        }
    except (cases.CaseConflict, QueueConflict, IdentityUnavailable):
        return None


@mutation_service
def request_review(*, token, reason, expected_case_ref, synthetic_fixtures_only=False):
    if type(reason) is not str or reason not in REASONS:
        raise cases.CaseConflict("access_review_reason_invalid")
    with cases._token_case(token, synthetic_fixtures_only) as case:
        if expected_case_ref != case.public_ref:
            raise cases.CaseConflict("access_review_case_changed")
        grant = RequesterTrackingToken.objects.get(pk=sha256(token.encode()).hexdigest())
        # The core case lock also serializes token rotation and concurrent requests.
        review, created = AccessReview.objects.get_or_create(
            grant=grant, defaults={"case": case, "reason": reason},
        )
        _verify_binding(review, case)
        return {**_public(review), "created": created}


@mutation_service
def staff_queue(*, subject_id, provider, synthetic_fixtures_only=False):
    cases._guard(synthetic_fixtures_only)
    try:
        identity = resolve_identity(provider, subject_id)
    except IdentityUnavailable as exc:
        raise cases.CaseConflict("access_review_staff_denied") from exc
    # Bound the operator list; closed requests remain in each requester's history.
    candidates = list(AccessReview.objects.filter(
        case__public_ref__in=identity.case_keys, state__in=("REQUESTED", "VERIFYING"),
    ).order_by("created_at").values_list("id", "case_id")[:50])
    rows = []
    for review_id, case_id in candidates:
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
            review = AccessReview.objects.select_related("grant").get(pk=review_id, case=case)
            _verify_binding(review, case)
            if review.state == "CLOSED":
                continue
            rows.append({**_public(review), "review_id": str(review.pk),
                         "public_ref": case.public_ref, "revision": review.revision,
                         "can_acknowledge": review.state == "REQUESTED",
                         "can_close": review.state == "VERIFYING" and review.grant.revoked_at is not None,
                         "old_access_revoked": review.grant.revoked_at is not None})
    return rows


@mutation_service
def advance_review(*, review_id, subject_id, provider, expected_revision, action,
                   synthetic_fixtures_only=False):
    cases._guard(synthetic_fixtures_only)
    if action not in {"acknowledge", "close"} or type(expected_revision) is not int:
        raise cases.CaseConflict("access_review_action_invalid")
    # A UUID is a selector only. Core identity and case scope are rechecked under lock.
    review = AccessReview.objects.filter(pk=cases._uuid(review_id)).first()
    if review is None:
        raise cases.CaseConflict("access_review_unavailable")
    with cases._staff_case(review.case_id, subject_id, provider, synthetic_fixtures_only) as (case, identity):
        review = AccessReview.objects.select_for_update().select_related("grant").get(pk=review.pk)
        _verify_binding(review, case)
        if review.revision != expected_revision:
            raise cases.CaseConflict("access_review_changed")
        if action == "acknowledge" and review.state == "REQUESTED":
            review.state, review.revision = "VERIFYING", 2
            review.acknowledged_at, review.acknowledged_by = timezone.now(), identity.subject_id
            review.save(update_fields=["state", "revision", "acknowledged_at", "acknowledged_by"])
        elif action == "close" and review.state == "VERIFYING" and review.grant.revoked_at is not None:
            review.state, review.revision = "CLOSED", 3
            review.closed_at, review.closed_by = timezone.now(), identity.subject_id
            review.save(update_fields=["state", "revision", "closed_at", "closed_by"])
        else:
            raise cases.CaseConflict("access_review_transition_denied")
        return _public(review)
