"""Append-only, case-scoped synthetic evaluation versions and human decisions."""

import uuid

from django.db import models
from django.db.models import Q


class EvaluationRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    corpus = models.JSONField()
    judgements = models.JSONField()
    corpus_sha256 = models.CharField(max_length=64)
    judgements_sha256 = models.CharField(max_length=64)
    ranker_version = models.CharField(max_length=160)
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "number"], name="ase_case_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="ase_version_bound"
            ),
        ]


class EvaluationDecision(models.Model):
    revision = models.OneToOneField(
        EvaluationRevision, on_delete=models.PROTECT, related_name="decision"
    )
    action = models.CharField(max_length=8)
    reviews = models.JSONField()
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=["APPROVE", "REJECT"]), name="ase_decision_kind"
            )
        ]
