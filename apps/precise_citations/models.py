"""Immutable phrase/source bindings. A correction always belongs to a new answer."""

import uuid

from django.db import models
from django.db.models import Q


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class CitationSet(Sealed):
    answer = models.OneToOneField(
        "casework.AnswerRevision", on_delete=models.PROTECT, related_name="precise_citation_set"
    )
    previous = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    request_key = models.UUIDField(unique=True)
    request_digest = models.CharField(max_length=64)
    count = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(count__gte=1, count__lte=12), name="precise_set_count"
            )
        ]


class CitationAnchor(Sealed):
    citation_set = models.ForeignKey(CitationSet, on_delete=models.PROTECT, related_name="anchors")
    ordinal = models.PositiveSmallIntegerField()
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    phrase = models.CharField(max_length=2000)
    source_case = models.ForeignKey("casework.Case", null=True, on_delete=models.PROTECT)
    source = models.JSONField()
    previous = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    correction_reason = models.CharField(max_length=2000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("citation_set", "ordinal"), name="precise_ordinal"),
            models.CheckConstraint(
                condition=Q(ordinal__gte=1, ordinal__lte=12), name="precise_ordinal_bound"
            ),
            models.CheckConstraint(
                condition=Q(end__gt=models.F("start")), name="precise_anchor_range"
            ),
        ]


class CitationReview(Sealed):
    citation_set = models.OneToOneField(
        CitationSet, on_delete=models.PROTECT, related_name="review"
    )
    action = models.CharField(max_length=8)
    note = models.CharField(max_length=2000)
    content_digest = models.CharField(max_length=64)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=("APPROVE", "REJECT")), name="precise_review_action"
            )
        ]
