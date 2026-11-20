import uuid

from django.db import models
from django.db.models import Q


class OrganizationRevision(models.Model):
    """Append-only metadata snapshot and optional internal note; never a case answer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    tags = models.JSONField(default=list)
    question_types = models.JSONField(default=list)
    note = models.TextField(blank=True)
    sha256 = models.CharField(max_length=64)
    command_id = models.UUIDField()
    command_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "version"], name="organization_version"),
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "command_id"],
                name="organization_command",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1, version__lte=256), name="organization_version_bound"
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$")
                & Q(command_sha256__regex=r"^[a-f0-9]{64}$"),
                name="organization_digests",
            ),
        ]
