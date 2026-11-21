"""Every permission change is an immutable, independently sealed audit revision."""

import uuid

from django.db import models
from django.db.models import Q


class PermissionRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=8)
    provider_id = models.CharField(max_length=128)
    scope_key = models.CharField(max_length=128)
    number = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=8)
    change = models.CharField(max_length=8)
    definition = models.JSONField()
    valid_until = models.DateTimeField(null=True)
    target_role = models.CharField(max_length=24, blank=True)
    target_auth_epoch = models.CharField(max_length=64, blank=True)
    target_scope_digest = models.CharField(max_length=64, blank=True)
    actor_provider_id = models.CharField(max_length=128)
    actor_subject_id = models.CharField(max_length=128)
    actor_role = models.CharField(max_length=24)
    actor_auth_epoch = models.CharField(max_length=64)
    policy_digest = models.CharField(max_length=64)
    context = models.JSONField()
    note = models.CharField(max_length=1000)
    request_key = models.UUIDField(unique=True)
    request_digest = models.CharField(max_length=64)
    reverted_from = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "provider_id", "scope_key", "number"), name="ps_scope_revision"
            ),
            models.CheckConstraint(condition=Q(kind__in=("SET", "USER")), name="ps_revision_kind"),
            models.CheckConstraint(
                condition=Q(state__in=("ACTIVE", "DISABLED")), name="ps_revision_state"
            ),
            models.CheckConstraint(
                condition=Q(change__in=("CREATE", "REPLACE", "DISABLE", "REVERT")),
                name="ps_revision_change",
            ),
            models.CheckConstraint(
                condition=Q(actor_role__in=("MUFTI", "ORGANIZER_ADMIN")),
                name="ps_administrative_actor",
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=256), name="ps_history_bound"
            ),
        ]
        indexes = [models.Index(fields=("kind", "provider_id", "scope_key"), name="ps_scope_index")]
