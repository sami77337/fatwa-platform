"""Immutable, replaceable derived generations; canonical sources remain elsewhere."""

import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q


class SearchGeneration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    profile = models.CharField(max_length=64)
    source_fingerprint = models.CharField(max_length=64)
    manifest = models.JSONField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    request_key = models.UUIDField()
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    transaction_id = models.BigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "number"], name="cs_generation_sequence"),
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="cs_generation_request",
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=128), name="cs_generation_bound"
            ),
        ]


class SearchDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation = models.ForeignKey(
        SearchGeneration, on_delete=models.PROTECT, related_name="documents"
    )
    ordinal = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=24)
    source_id = models.UUIDField()
    pin = models.JSONField()
    original_text = models.TextField()
    normalized_text = models.TextField()
    vector = SearchVectorField(default="", editable=False)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["generation", "ordinal"], name="cs_document_ordinal"),
            models.CheckConstraint(
                condition=Q(ordinal__gte=1, ordinal__lte=512), name="cs_document_bound"
            ),
            models.CheckConstraint(
                condition=Q(
                    kind__in=[
                        "QUESTION",
                        "FOLLOWUP",
                        "ANSWER",
                        "TRANSCRIPT",
                        "RECORDING_TRANSCRIPT",
                    ]
                ),
                name="cs_document_kind",
            ),
        ]
        indexes = [
            GinIndex(fields=["vector"], name="cs_document_fts_gin"),
            GinIndex(
                fields=["normalized_text"], opclasses=["gin_trgm_ops"], name="cs_document_trgm_gin"
            ),
        ]
