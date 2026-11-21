import uuid

from django.db import models

from .contract import PURPOSES, STATUSES


class Sealed(models.Model):
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class QuarantinedFile(Sealed):
    sha256 = models.CharField(primary_key=True, max_length=64)
    size = models.PositiveIntegerField()
    original = models.BinaryField()


class UploadAdmission(Sealed):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(QuarantinedFile, on_delete=models.PROTECT)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    purpose = models.CharField(max_length=32)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    request_digest = models.CharField(max_length=64, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(purpose__in=sorted(PURPOSES)), name="upload_security_purpose"
            )
        ]


class ScanAttempt(Sealed):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(QuarantinedFile, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    previous_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=24)
    scanner = models.JSONField()
    policy = models.JSONField()
    complete = models.BooleanField(default=False)
    scanned_files = models.PositiveIntegerField(default=0)
    loaded_signatures = models.PositiveIntegerField(default=0)
    valid_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=STATUSES), name="upload_security_status"
            ),
            models.UniqueConstraint(
                fields=["file", "sequence"], name="upload_security_attempt_order"
            ),
        ]
