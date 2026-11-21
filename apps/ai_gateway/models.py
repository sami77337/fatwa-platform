"""Attempts and terminal audit are immutable; candidates are separate derivatives."""

import uuid

from django.db import models
from django.db.models import Q


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class GatewayRun(Sealed):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    identity_provider = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    request_key = models.UUIDField(unique=True)
    request_digest = models.CharField(max_length=64)
    task = models.CharField(max_length=32)
    task_version = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=128, blank=True)
    model_id = models.CharField(max_length=128, blank=True)
    model_version = models.CharField(max_length=128, blank=True)
    adapter_version = models.CharField(max_length=128, blank=True)
    provider_mode = models.CharField(max_length=16)
    expected_revision = models.PositiveIntegerField()
    expected_evidence_version = models.PositiveIntegerField()
    query_digest = models.CharField(max_length=64)
    context_digest = models.CharField(max_length=64)
    source = models.JSONField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(task="CITATION_CANDIDATES"), name="ai_gateway_only_task"
            )
        ]


class GatewayOutcome(Sealed):
    run = models.OneToOneField(GatewayRun, on_delete=models.PROTECT, related_name="outcome")
    status = models.CharField(max_length=24)
    output_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "SUCCEEDED",
                        "PROVIDER_UNAVAILABLE",
                        "PROVIDER_FAILED",
                        "OUTPUT_REJECTED",
                        "REVOKED",
                    )
                ),
                name="ai_gateway_outcome_status",
            )
        ]


class CandidateBatch(Sealed):
    run = models.OneToOneField(GatewayRun, on_delete=models.PROTECT, related_name="batch")
    entries = models.JSONField()
