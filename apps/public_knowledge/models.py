"""Immutable public curation versions, decisions and exact expiring release leases."""

import uuid

from django.db import models
from django.db.models import Q


class PublicSeries(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    author_provider = models.CharField(max_length=128, blank=True)
    author_subject = models.CharField(max_length=128, blank=True)
    publication = models.ForeignKey(
        "experimental_publication.PublicationEdition", null=True, on_delete=models.PROTECT
    )
    language = models.CharField(max_length=16, blank=True)
    external_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("SCHOLAR", "TOPIC", "PRESENTATION", "LESSON")),
                name="pk_series_kind",
            ),
            models.UniqueConstraint(
                fields=["author_provider", "author_subject"],
                condition=Q(kind="SCHOLAR"),
                name="pk_scholar_identity",
            ),
            models.UniqueConstraint(
                fields=["publication", "language"],
                condition=Q(kind="PRESENTATION"),
                name="pk_publication_language",
            ),
            models.UniqueConstraint(
                fields=["external_id"], condition=Q(kind="LESSON"), name="pk_lesson_identity"
            ),
        ]


class PublicRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.ForeignKey(PublicSeries, on_delete=models.PROTECT, related_name="revisions")
    publication = models.ForeignKey(
        "experimental_publication.PublicationEdition", on_delete=models.PROTECT
    )
    number = models.PositiveIntegerField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    request_key = models.UUIDField(unique=True)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="pk_revision_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=128), name="pk_revision_bound"
            ),
        ]


class PublicAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(PublicRevision, on_delete=models.PROTECT, related_name="actions")
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    request_key = models.UUIDField(unique=True)
    note = models.CharField(max_length=2000, blank=True)
    # RELEASE is a lease on this exact immutable payload, never a general grant.
    content_sha256 = models.CharField(max_length=64)
    expires_at = models.DateTimeField(null=True)
    requested_minutes = models.PositiveSmallIntegerField(default=0)
    related = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "sequence"], name="pk_action_sequence"),
            models.UniqueConstraint(
                fields=["revision", "action"],
                condition=Q(action__in=("REVIEW", "APPROVE", "WITHDRAW")),
                name="pk_single_decision",
            ),
            models.UniqueConstraint(
                fields=["related"], condition=Q(action="REVOKE"), name="pk_single_revocation"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=256), name="pk_action_bound"
            ),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW")),
                name="pk_action_kind",
            ),
        ]
