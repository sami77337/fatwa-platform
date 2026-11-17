"""Immutable editorial copies and independent publication decisions; synthetic only."""

import uuid

from django.db import models
from django.db.models import Q


class PublicationEdition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    answer = models.ForeignKey("casework.AnswerRevision", on_delete=models.PROTECT)
    decision = models.ForeignKey("casework.CaseDecision", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=80)
    body = models.TextField()
    citations = models.JSONField(default=list)
    content_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "number"], name="ep_edition_number"),
            models.CheckConstraint(condition=Q(number__gte=1), name="ep_number_positive"),
        ]


class PublicationAction(models.Model):
    edition = models.ForeignKey(
        PublicationEdition, on_delete=models.PROTECT, related_name="actions"
    )
    action = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["edition", "action"], name="ep_action_once"),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "APPROVE", "WITHDRAW")), name="ep_action_kind"
            ),
        ]
