"""One immutable binding to the existing queue, never a second delivery engine."""

from django.db import models


class CompositeDelivery(models.Model):
    decision = models.OneToOneField(
        "casework.CaseDecision", primary_key=True, on_delete=models.PROTECT
    )
    approval = models.OneToOneField("delivery_queue.ApprovalClaim", on_delete=models.PROTECT)
    manifest_sha256 = models.CharField(max_length=64)
    capability_sha256 = models.CharField(max_length=64)
    selection_mode = models.CharField(max_length=16, default="ALL")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(selection_mode__in=["ALL", "TEXT_ONLY"]),
                name="composite_selection_kind",
            )
        ]


class CompositeRetry(models.Model):
    """One explicitly approved successor; the failed queue attempt is immutable."""

    id = models.UUIDField(primary_key=True, editable=False)
    delivery = models.ForeignKey(CompositeDelivery, on_delete=models.PROTECT)
    parent_intent = models.OneToOneField("delivery_queue.DeliveryIntent", on_delete=models.PROTECT)
    approval = models.OneToOneField("delivery_queue.ApprovalClaim", on_delete=models.PROTECT)
    part = models.ForeignKey("answer_media.AnswerPart", on_delete=models.PROTECT)
    failure_evidence = models.ForeignKey(
        "delivery_queue.ProviderSignatureEvidence", on_delete=models.PROTECT
    )
    logical_ordinal = models.PositiveSmallIntegerField()
    retry_number = models.PositiveSmallIntegerField()
    scope = models.JSONField()
    canonical_payload = models.TextField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "logical_ordinal", "retry_number"],
                name="composite_retry_part_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(logical_ordinal__gte=1, logical_ordinal__lte=16),
                name="composite_retry_logical_ordinal",
            ),
            models.CheckConstraint(
                condition=models.Q(retry_number__gte=1, retry_number__lte=3),
                name="composite_retry_bounded_number",
            ),
        ]
