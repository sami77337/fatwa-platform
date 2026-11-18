"""V12 extends the existing one-case synthetic fixture, never seeds human approvals."""

from pathlib import Path

from tests.casework.v11_fixtures import DRAFT
from tests.casework.v11_fixtures import inventory as v11_inventory

OUT = Path(".local/qa/v12/browser")
APPROVED_TEXT = DRAFT + " تمت مراجعة ترتيب الملف والصوت في هذا الإصدار."


def inventory(case_id):
    from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent, ProviderReceipt

    result = v11_inventory(case_id)
    from apps.casework.models import Case

    intents = DeliveryIntent.objects.filter(case_key=Case.objects.get(pk=case_id).public_ref)
    result["delivery"] = {
        "parts": list(intents.order_by("ordinal").values("ordinal", "state", "payload_sha256")),
        "attempts": DeliveryAttempt.objects.filter(intent__in=intents).count(),
        "receipts": ProviderReceipt.objects.filter(intent__in=intents).count(),
    }
    return result
