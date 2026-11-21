"""Append-only human labels, separate from canonical source and grant records."""

import uuid

from django.db import models
from django.db.models import Q

from .catalog import LEVELS, TARGETS


class ClassificationRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_kind = models.CharField(max_length=24)
    target_id = models.UUIDField()
    case = models.ForeignKey("casework.Case", null=True, on_delete=models.PROTECT)
    source_digest = models.CharField(max_length=64)
    number = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    level = models.CharField(max_length=16)
    note = models.CharField(max_length=1000)
    request_key = models.UUIDField(unique=True)
    request_digest = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    policy_digest = models.CharField(max_length=64)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("target_kind", "target_id", "number"), name="dp_target_revision"
            ),
            models.CheckConstraint(condition=Q(level__in=LEVELS), name="dp_classification_level"),
            models.CheckConstraint(
                condition=Q(target_kind__in=tuple(TARGETS)), name="dp_target_kind"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=256), name="dp_history_bound"
            ),
        ]
        indexes = [models.Index(fields=("target_kind", "target_id"), name="dp_target_index")]
