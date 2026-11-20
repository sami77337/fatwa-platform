"""Immutable staging, plans, independent decisions and canonical application receipts."""

import uuid

from django.db import models
from django.db.models import Q


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    request_key = models.UUIDField()
    namespace = models.CharField(max_length=100)
    filename = models.CharField(max_length=160)
    format = models.CharField(max_length=5)
    raw = models.BinaryField()
    raw_sha256 = models.CharField(max_length=64)
    provenance = models.TextField()
    rights_basis = models.TextField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "namespace", "raw_sha256"], name="mi_batch_exact_source"
            ),
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="mi_batch_request_once",
            ),
            models.CheckConstraint(
                condition=Q(format__in=["csv", "json", "jsonl", "zip"]), name="mi_batch_format"
            ),
            models.CheckConstraint(
                condition=Q(namespace__regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$"),
                name="mi_batch_namespace",
            ),
        ]


class MappingRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, related_name="mappings", on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    mapping = models.JSONField()
    resolutions = models.JSONField(default=dict)
    digest = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "number"], name="mi_mapping_sequence"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=32), name="mi_mapping_bound"
            ),
        ]


class ImportPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, related_name="plans", on_delete=models.PROTECT)
    mapping = models.ForeignKey(MappingRevision, on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    report = models.JSONField()
    digest = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "number"], name="mi_plan_sequence"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=32), name="mi_plan_bound"
            ),
        ]


class ImportDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.OneToOneField(ImportPlan, related_name="decision", on_delete=models.PROTECT)
    verdict = models.CharField(max_length=8)
    note = models.TextField()
    verification_note = models.TextField()
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(verdict__in=["APPROVE", "REJECT"]), name="mi_decision_verdict"
            )
        ]


class GroupResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(ImportPlan, related_name="groups", on_delete=models.PROTECT)
    group_key = models.CharField(max_length=100)
    outcomes = models.JSONField()
    digest = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "group_key"], name="mi_group_applied_once")
        ]


class ImportEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, related_name="events", on_delete=models.PROTECT)
    sequence = models.PositiveSmallIntegerField()
    request_key = models.UUIDField()
    action = models.CharField(max_length=12)
    detail = models.JSONField()
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    previous_digest = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "sequence"], name="mi_event_sequence"),
            models.UniqueConstraint(fields=["batch", "request_key"], name="mi_event_request_once"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=128), name="mi_event_bound"
            ),
            models.CheckConstraint(
                condition=Q(
                    action__in=[
                        "STAGE",
                        "MAP",
                        "RESOLVE",
                        "PLAN",
                        "APPROVE",
                        "REJECT",
                        "APPLY",
                        "FAIL",
                        "CANCEL",
                    ]
                ),
                name="mi_event_action",
            ),
        ]


class RoundtripReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    request_key = models.UUIDField()
    scope = models.JSONField()
    scope_digest = models.CharField(max_length=64)
    manifest = models.JSONField()
    artifact_sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="mi_roundtrip_once",
            ),
            models.CheckConstraint(
                condition=Q(size__gte=1, size__lte=192000), name="mi_roundtrip_bound"
            ),
        ]
