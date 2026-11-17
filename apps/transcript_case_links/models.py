import uuid

from django.db import models


class TranscriptUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    bundle = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class TranscriptLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    upload = models.ForeignKey(TranscriptUpload, on_delete=models.PROTECT)
    evidence = models.OneToOneField("casework.CaseEvidence", on_delete=models.PROTECT)
    event = models.OneToOneField("casework.CaseEvent", on_delete=models.PROTECT)
    external_id = models.CharField(max_length=100)
    question_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "external_id"], name="transcript_case_source_once"
            )
        ]
