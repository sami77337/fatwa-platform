"""Immutable decisions; optional private reasons are absent from the external journal."""

import uuid

from django.db import models


class SuppressionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ledger_id = models.UUIDField()
    sequence = models.PositiveIntegerField(unique=True)
    target_kind = models.CharField(max_length=32)
    target_id = models.UUIDField()
    source_digest = models.CharField(max_length=64)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT, null=True)
    version = models.PositiveIntegerField()
    previous_state = models.CharField(max_length=16)
    state = models.CharField(max_length=16)
    action = models.CharField(max_length=16)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    role = models.CharField(max_length=32)
    auth_epoch = models.CharField(max_length=128)
    reason_sha256 = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    previous_digest = models.CharField(max_length=64)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    recovered = models.BooleanField(default=False)
    recovery_reason = models.TextField(blank=True)
    applied_provider_id = models.CharField(max_length=128)
    applied_subject_id = models.CharField(max_length=128)
    applied_role = models.CharField(max_length=32)
    applied_auth_epoch = models.CharField(max_length=128)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("target_kind", "target_id", "version"), name="rs_target_version"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sequence__gte=1, sequence__lte=4096, version__gte=1, version__lte=4096
                ),
                name="rs_numbers",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("SOFT_DELETED", "RESTORED")), name="rs_state"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=("SOFT_DELETE", "RESTORE")), name="rs_action"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    role__in=("MUFTI", "ORGANIZER_ADMIN"),
                    applied_role__in=("MUFTI", "ORGANIZER_ADMIN"),
                ),
                name="rs_actual_roles",
            ),
        ]
