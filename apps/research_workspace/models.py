"""Private research references, never copies of source material or access grants."""

import uuid

from django.db import models
from django.db.models import Q


class ResearchCollection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    title = models.CharField(max_length=160)
    revision = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(revision__lte=256), name="research_collection_revision_bound"
            ),
            models.CheckConstraint(
                condition=Q(title__regex=r"\S"), name="research_collection_title_present"
            ),
        ]
        indexes = [models.Index(fields=["case", "provider_id", "subject_id"])]


class ResearchItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(
        ResearchCollection, related_name="items", on_delete=models.PROTECT
    )
    resource = models.JSONField()
    resource_sha256 = models.CharField(max_length=64)
    ordinal = models.PositiveIntegerField()
    note = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "resource_sha256"], name="research_collection_exact_item"
            ),
            models.UniqueConstraint(
                fields=["collection", "ordinal"], name="research_collection_item_position"
            ),
            models.CheckConstraint(
                condition=Q(ordinal__gte=1, ordinal__lte=60), name="research_item_position_bound"
            ),
        ]


class SavedResearchSearch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(
        ResearchCollection, related_name="searches", on_delete=models.PROTECT
    )
    title = models.CharField(max_length=160)
    filters = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class ResearchCollectionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(
        ResearchCollection, related_name="events", on_delete=models.PROTECT
    )
    revision = models.PositiveIntegerField()
    action = models.CharField(max_length=24)
    details = models.JSONField(default=dict)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    state_sha256 = models.CharField(max_length=64)
    previous_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "revision"], name="research_collection_event_revision"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1, revision__lte=256),
                name="research_collection_event_bound",
            ),
        ]
