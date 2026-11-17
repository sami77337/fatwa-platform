"""Private original bytes: never a media/static URL or an overwriteable file."""

import uuid

from django.db import models
from django.db.models import Q


class CaseAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    evidence = models.OneToOneField("casework.CaseEvidence", on_delete=models.PROTECT)
    event = models.OneToOneField("casework.CaseEvent", on_delete=models.PROTECT)
    original = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    media_type = models.CharField(max_length=40, default="text/plain")
    kind = models.CharField(max_length=8, default="text")
    validation_metadata = models.JSONField(default=dict)
    filename = models.CharField(max_length=100)
    source = models.CharField(max_length=24, default="REQUESTER_UPLOAD")
    subject_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(size__gte=1, size__lte=192000), name="ca_size"),
            models.CheckConstraint(
                condition=Q(
                    media_type__in=(
                        "text/plain",
                        "application/pdf",
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                        "audio/mpeg",
                        "audio/mp4",
                        "audio/wav",
                    )
                ),
                name="ca_type",
            ),
            models.CheckConstraint(condition=Q(source="REQUESTER_UPLOAD"), name="ca_source"),
            models.CheckConstraint(condition=Q(sha256__regex=r"^[a-f0-9]{64}$"), name="ca_digest"),
        ]
