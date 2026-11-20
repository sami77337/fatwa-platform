"""Immutable export scope, append-only attempts, and private durable result bytes."""

import uuid

from django.db import models
from django.db.models import Q


class ExportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    request_key = models.UUIDField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    selection = models.JSONField()
    selection_sha256 = models.CharField(max_length=64)
    format = models.CharField(max_length=5)
    include_files = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="selected_export_prepare_once",
            ),
            models.CheckConstraint(
                condition=Q(format__in=["JSON", "CSV", "JSONL"]), name="selected_export_format"
            ),
        ]


class ExportArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ExportJob, related_name="artifacts", on_delete=models.PROTECT)
    attempt = models.PositiveIntegerField()
    raw = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    manifest = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "attempt"], name="selected_export_artifact_once"
            ),
            models.CheckConstraint(
                condition=Q(size__gte=1, size__lte=8388608), name="selected_export_size"
            ),
            models.CheckConstraint(
                condition=Q(attempt__gte=1, attempt__lte=10),
                name="selected_export_artifact_attempt",
            ),
        ]


class ExportEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ExportJob, related_name="events", on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    request_key = models.UUIDField()
    action = models.CharField(max_length=12)
    state = models.CharField(max_length=12)
    attempt = models.PositiveIntegerField(default=0)
    lease_id = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    completed = models.PositiveIntegerField(default=0)
    outcomes = models.JSONField(default=list)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    previous_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "sequence"], name="selected_export_event_sequence"
            ),
            models.UniqueConstraint(
                fields=["job", "request_key"], name="selected_export_event_once"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=96), name="selected_export_event_bound"
            ),
            models.CheckConstraint(
                condition=Q(attempt__lte=10), name="selected_export_attempt_bound"
            ),
            models.CheckConstraint(
                condition=Q(completed__lte=20), name="selected_export_completed_bound"
            ),
        ]
