"""Append-only knowledge relationship revisions; canonical sources stay in their apps."""

import uuid

from django.db import models
from django.db.models import Q


class KnowledgeRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.UUIDField(default=uuid.uuid4)
    number = models.PositiveIntegerField()
    publication = models.ForeignKey(
        "experimental_publication.PublicationEdition", on_delete=models.PROTECT
    )
    heading = models.ForeignKey("reference.ReferenceHeading", null=True, on_delete=models.PROTECT)
    transcript = models.ForeignKey(
        "transcript_case_links.TranscriptLink", null=True, on_delete=models.PROTECT
    )
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    reason = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="knowledge_revision_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="knowledge_revision_bound"
            ),
            models.CheckConstraint(
                condition=(
                    Q(heading__isnull=False, transcript__isnull=True)
                    | Q(heading__isnull=True, transcript__isnull=False)
                ),
                name="knowledge_exact_target",
            ),
        ]


class KnowledgeAction(models.Model):
    revision = models.ForeignKey(
        KnowledgeRevision, related_name="actions", on_delete=models.PROTECT
    )
    action = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "action"], name="knowledge_action_once"),
            models.CheckConstraint(
                condition=Q(action__in=["APPROVE", "WITHDRAW"]), name="knowledge_action_kind"
            ),
        ]
