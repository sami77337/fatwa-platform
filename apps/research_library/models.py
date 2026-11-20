"""Source identities, exact editions/files, and independently reviewed use leases."""

import uuid

from django.db import models
from django.db.models import Q


class LibraryBlob(models.Model):
    sha256 = models.CharField(primary_key=True, max_length=64)
    original = models.BinaryField(null=True)
    storage_backend = models.CharField(max_length=32)
    storage_key = models.CharField(max_length=69)
    size = models.PositiveIntegerField()
    media_type = models.CharField(max_length=80)
    validation = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(size__gte=1, size__lte=192000), name="rl_blob_size"),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$"), name="rl_blob_hash"
            ),
        ]


class LibraryItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    namespace = models.CharField(max_length=100)
    external_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "namespace", "external_id"], name="rl_source_identity"
            ),
        ]


class LibraryVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(LibraryItem, related_name="versions", on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    previous = models.OneToOneField("self", null=True, on_delete=models.PROTECT)
    payload = models.JSONField()
    blob = models.ForeignKey(LibraryBlob, null=True, on_delete=models.PROTECT)
    filename = models.CharField(max_length=100, blank=True)
    request_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "number"], name="rl_version_number"),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"], name="rl_write_request"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="rl_version_bound"
            ),
            models.CheckConstraint(
                condition=Q(digest__regex=r"^[a-f0-9]{64}$"), name="rl_version_hash"
            ),
        ]


class LibraryDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(LibraryVersion, related_name="decisions", on_delete=models.PROTECT)
    sequence = models.PositiveSmallIntegerField()
    action = models.CharField(max_length=12)
    uses = models.JSONField(default=list)
    valid_until = models.DateTimeField(null=True)
    note = models.CharField(max_length=1000)
    request_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    previous_digest = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "sequence"], name="rl_decision_sequence"),
            models.UniqueConstraint(fields=["version", "action"], name="rl_decision_once"),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"], name="rl_decision_request"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=5), name="rl_decision_bound"
            ),
            models.CheckConstraint(
                condition=Q(action__in=["REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW"]),
                name="rl_decision_action",
            ),
            models.CheckConstraint(
                condition=Q(digest__regex=r"^[a-f0-9]{64}$"), name="rl_decision_hash"
            ),
        ]
