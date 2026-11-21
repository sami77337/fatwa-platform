"""Immutable metadata audit; derivative payloads remain owned by their original apps."""

import uuid

from django.db import models


class DerivativeClear(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ledger_id = models.UUIDField()
    sequence = models.PositiveIntegerField(unique=True)
    previous_digest = models.CharField(max_length=64)
    kind = models.CharField(max_length=24)
    target_id = models.UUIDField()
    header_digest = models.CharField(max_length=64)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    payload = models.JSONField()
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    role = models.CharField(max_length=32)
    auth_epoch = models.CharField(max_length=128)
    reason_sha256 = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    recovered = models.BooleanField(default=False)
    recovery_reason = models.TextField(blank=True)
    applied_provider_id = models.CharField(max_length=128)
    applied_subject_id = models.CharField(max_length=128)
    applied_role = models.CharField(max_length=32)
    applied_auth_epoch = models.CharField(max_length=128)
    transaction_id = models.BigIntegerField(default=0, editable=False)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("kind", "target_id"), name="dm_clear_target_once"),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1, sequence__lte=4096), name="dm_clear_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=("SEARCH_INDEX", "AI_CANDIDATES")), name="dm_clear_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    role__in=("MUFTI", "ORGANIZER_ADMIN"),
                    applied_role__in=("MUFTI", "ORGANIZER_ADMIN"),
                ),
                name="dm_clear_roles",
            ),
        ]


class DerivativeRebuild(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clearance = models.ForeignKey(
        DerivativeClear, on_delete=models.PROTECT, related_name="rebuilds"
    )
    child_id = models.UUIDField()
    child_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=24)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=128)
    role = models.CharField(max_length=32)
    reason = models.TextField()
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("clearance", "child_id"), name="dm_rebuild_child_once"),
            models.CheckConstraint(
                condition=models.Q(role="MUFTI"), name="dm_rebuild_actual_mufti"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "SUCCEEDED",
                        "PROVIDER_UNAVAILABLE",
                        "PROVIDER_FAILED",
                        "OUTPUT_REJECTED",
                    )
                ),
                name="dm_rebuild_status",
            ),
        ]
