import uuid

from django.db import models


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class DerivativeJob(Sealed):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    attachment = models.ForeignKey(
        "case_attachments.CaseAttachment", null=True, on_delete=models.PROTECT
    )
    answer_part = models.ForeignKey("answer_media.AnswerPart", null=True, on_delete=models.PROTECT)
    library_version = models.ForeignKey(
        "research_library.LibraryVersion", null=True, on_delete=models.PROTECT
    )
    origin_session = models.ForeignKey(
        "staff_sessions.Session", null=True, on_delete=models.PROTECT
    )
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    claims_digest = models.CharField(max_length=64)
    source = models.JSONField()
    source_digest = models.CharField(max_length=64)
    task = models.CharField(max_length=24)
    recipe_version = models.CharField(max_length=64)
    request_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    execute_until = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="derivative_job_request",
            ),
            models.CheckConstraint(
                condition=models.Q(task__in=("THUMBNAIL", "AUDIO_PLAYBACK")),
                name="derivative_job_task",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        attachment__isnull=False,
                        answer_part__isnull=True,
                        library_version__isnull=True,
                    )
                    | models.Q(
                        attachment__isnull=True,
                        answer_part__isnull=False,
                        library_version__isnull=True,
                    )
                    | models.Q(
                        attachment__isnull=True,
                        answer_part__isnull=True,
                        library_version__isnull=False,
                    )
                ),
                name="derivative_one_original",
            ),
        ]


class DerivedOutput(Sealed):
    job = models.ForeignKey(DerivativeJob, on_delete=models.PROTECT, related_name="outputs")
    attempt = models.PositiveIntegerField()
    lease = models.UUIDField()
    source_digest = models.CharField(max_length=64)
    recipe_version = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    raw = models.BinaryField()
    media_type = models.CharField(max_length=32)
    metadata = models.JSONField()
    engine = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "attempt"], name="derivative_output_attempt")
        ]


class DerivativeEvent(Sealed):
    job = models.ForeignKey(DerivativeJob, on_delete=models.PROTECT, related_name="events")
    sequence = models.PositiveIntegerField()
    request_key = models.UUIDField()
    action = models.CharField(max_length=16)
    state = models.CharField(max_length=16)
    attempt = models.PositiveIntegerField()
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    output = models.ForeignKey(DerivedOutput, on_delete=models.PROTECT, null=True)
    code = models.CharField(max_length=32)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    engine = models.JSONField(default=dict)
    previous_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "sequence"], name="derivative_event_order"),
            models.UniqueConstraint(fields=["job", "request_key"], name="derivative_event_request"),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=("QUEUED", "RUNNING", "READY", "FAILED", "UNAVAILABLE", "CANCELLED")
                ),
                name="derivative_event_state",
            ),
        ]
