"""Use the existing core locks, capability checks and trusted scoped identities.

No function here issues, rotates, revokes, delivers, or restores a capability.
Private core context managers are intentionally reused at the pinned V6 boundary.
"""
from hashlib import sha256

from django.utils import timezone

from apps.casework import delivery, services as cases
from apps.delivery_queue.models import RequesterTrackingToken
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity

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
            if answer is None or answer.decision_id != decision.pk:
                raise cases.CaseConflict("current_private_answer_unavailable")
            private_answer = {"text": answer.text, "revision": answer.revision}
        reviews = list(AccessReview.objects.filter(case=case).select_related("grant")
                       .order_by("-created_at")[:10])
        for review in reviews:
            _verify_binding(review, case)
        return {
            "case": result,
            "reviews": [_public(review) for review in reviews],
            "private_answer": private_answer,
        }


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
