"""Review ledger only; existing publication categories and knowledge sources stay canonical."""

import uuid

from django.db import models
from django.db.models import Q


class ClassificationRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.UUIDField(default=uuid.uuid4)
    number = models.PositiveIntegerField()
    knowledge = models.ForeignKey("knowledge_links.KnowledgeRevision", on_delete=models.PROTECT)
    label = models.CharField(max_length=80)
    reason = models.CharField(max_length=1000)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="classification_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="classification_number_bound"
            ),
        ]


class ClassificationAction(models.Model):
    revision = models.ForeignKey(
        ClassificationRevision, related_name="actions", on_delete=models.PROTECT
    )
    action = models.CharField(max_length=16)
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "action"], name="classification_action_once"
            ),
            models.UniqueConstraint(
                fields=["revision"],
                condition=Q(action__in=["APPROVE", "REJECT"]),
                name="classification_one_decision",
            ),
            models.CheckConstraint(
                condition=Q(action__in=["APPROVE", "REJECT", "WITHDRAW"]),
                name="classification_action_kind",
            ),
        ]
