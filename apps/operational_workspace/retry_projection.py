"""Read exact successful retry ancestry without authorizing a retry or changing history."""

from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import CaseDelivery
from apps.composite_delivery import retries
from apps.composite_delivery.models import CompositeDelivery, CompositeRetry
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier


def configuration():
    """Pure current verifier/config pins; unversioned external key status cannot hide failures."""
    enabled = getattr(settings, "FATWA_COMPOSITE_RETRY_ENABLED", False)
    composite = getattr(settings, "FATWA_COMPOSITE_DELIVERY_ENABLED", False)
    verifier = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
    base = (type(enabled), enabled, type(composite), composite, id(verifier))
    if not isinstance(verifier, Ed25519ProviderEventVerifier):
        return (*base, "UNAVAILABLE")
    status = verifier._key_status
    if status is None:
        status_epoch = "STATIC_CURRENT_KEYS"
    else:
        try:
            status_epoch = status.projection_epoch()
        except Exception:
            status_epoch = "UNVERSIONED"
        if type(status_epoch) is not str or not 1 <= len(status_epoch) <= 131072:
            status_epoch = "UNVERSIONED"
    return (*base, retries._trust(verifier), status_epoch)


def read(case):
    bound = set(
        CaseDelivery.objects.filter(decision__case=case).values_list("approval_id", flat=True)
    )
    roots = list(
        CompositeDelivery.objects.filter(decision__case=case).select_related(
            "decision__case", "decision__answer", "approval"
        )
    )
    bound.update(row.approval_id for row in roots)
    records = list(
        CompositeRetry.objects.filter(delivery__decision__case=case).select_related("approval")
    )
    bound.update(row.approval_id for row in records)
    claims = set(
        ApprovalClaim.objects.filter(case_key=case.public_ref).values_list("pk", flat=True)
    )
    result = {
        "resolved": [],
        "logical": {},
        "unbound_claims": sorted(claims - bound),
        "verification_issue": False,
    }
    if not records:
        return result
    current = configuration()
    if (
        current[1] is not True
        or current[3] is not True
        or current[-1] in {"UNAVAILABLE", "UNVERSIONED"}
    ):
        result["verification_issue"] = True
        return result
    verifier = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
    resolved = set()
    for root in roots:
        selected = [row for row in records if row.delivery_id == root.pk]
        if not selected:
            continue
        try:
            status = retries.status_locked(root, verifier)
        except (cases.CaseConflict, ValueError):
            result["verification_issue"] = True
            continue
        for part in status["parts"]:
            if part["delivery_verified"] is True:
                resolved.update(row["failed_intent"] for row in part["retry_history"])
        for row in selected:
            child = DeliveryIntent.objects.get(approval=row.approval)
            result["logical"][child.pk] = {
                "ordinal": row.logical_ordinal,
                "retry_number": row.retry_number,
            }
    result["resolved"] = sorted(resolved)
    return result
