"""Append-only human curation. No original text or source bytes are copied here."""

import uuid

from django.db import models
from django.db.models import Q


class CollectionSeries(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("TOPIC", "COLLECTION", "HOME")), name="pcol_kind"
            ),
        ]


class CollectionRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.ForeignKey(CollectionSeries, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT, related_name="children")
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    request_key = models.UUIDField(unique=True)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("series", "number"), name="pcol_revision_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=128), name="pcol_revision_bound"
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$"), name="pcol_revision_sha"
            ),
        ]


class CollectionAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(
        CollectionRevision, on_delete=models.PROTECT, related_name="actions"
    )
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    request_key = models.UUIDField(unique=True)
    note = models.CharField(max_length=2000, blank=True)
    content_sha256 = models.CharField(max_length=64)
    expires_at = models.DateTimeField(null=True)
    requested_minutes = models.PositiveSmallIntegerField(default=0)
    related = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("revision", "sequence"), name="pcol_action_sequence"),
            models.UniqueConstraint(
                fields=("revision", "action"),
                condition=Q(action__in=("REVIEW", "APPROVE", "WITHDRAW")),
                name="pcol_single_decision",
            ),
            models.UniqueConstraint(
                fields=("related",), condition=Q(action="REVOKE"), name="pcol_single_revocation"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=256), name="pcol_action_bound"
            ),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW")),
                name="pcol_action_kind",
            ),
        ]
