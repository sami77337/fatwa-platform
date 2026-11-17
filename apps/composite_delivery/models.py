"""One immutable binding to the existing queue, never a second delivery engine."""

from django.db import models


class CompositeDelivery(models.Model):
    decision = models.OneToOneField(
        "casework.CaseDecision", primary_key=True, on_delete=models.PROTECT
    )
    approval = models.OneToOneField("delivery_queue.ApprovalClaim", on_delete=models.PROTECT)
    manifest_sha256 = models.CharField(max_length=64)
    capability_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
