"""Immutable authored answer parts; never requester evidence attachments."""

import uuid

from django.db import models
from django.db.models import Q


class AnswerManifest(models.Model):
    answer = models.OneToOneField(
        "casework.AnswerRevision",
        primary_key=True,
        on_delete=models.PROTECT,
        related_name="media_manifest",
    )
    sha256 = models.CharField(max_length=64)
    part_count = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(part_count__gte=2, part_count__lte=8), name="am_count"
            ),
            models.CheckConstraint(condition=Q(sha256__regex=r"^[a-f0-9]{64}$"), name="am_digest"),
        ]


class AnswerPart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manifest = models.ForeignKey(AnswerManifest, on_delete=models.PROTECT, related_name="parts")
    ordinal = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=12)
    original = models.BinaryField(null=True)
    storage_backend = models.CharField(max_length=32, default="inline-database-v1")
    storage_key = models.CharField(max_length=69, default="")
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    media_type = models.CharField(max_length=80)
    filename = models.CharField(max_length=120)
    metadata = models.JSONField(default=dict)
    source = models.CharField(max_length=24, default="MUFTI_AUTHORED")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["manifest", "ordinal"], name="am_ordinal_unique"),
            models.CheckConstraint(condition=Q(ordinal__gte=1, ordinal__lte=8), name="am_ordinal"),
            models.CheckConstraint(
                condition=Q(kind__in=("TEXT", "FILE", "AUDIO", "IMAGE")), name="am_kind"
            ),
            models.CheckConstraint(condition=Q(size__gte=1, size__lte=192000), name="am_size"),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$"), name="am_part_digest"
            ),
            models.CheckConstraint(condition=Q(source="MUFTI_AUTHORED"), name="am_source"),
        ]


class PrivateAnswerRelease(models.Model):
    """Explicit private portal availability, not delivery or reading evidence."""

    manifest = models.OneToOneField(AnswerManifest, primary_key=True, on_delete=models.PROTECT)
    decision = models.OneToOneField("casework.CaseDecision", on_delete=models.PROTECT)
    evidence_version = models.PositiveIntegerField()
    manifest_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
