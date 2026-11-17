"""An immutable source snapshot belonging to one canonical answer revision."""

import uuid

from django.db import models


class AnswerCitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    answer = models.ForeignKey(
        "casework.AnswerRevision", on_delete=models.PROTECT, related_name="citations"
    )
    heading = models.ForeignKey("reference.ReferenceHeading", on_delete=models.PROTECT)
    ordinal = models.PositiveSmallIntegerField()
    source = models.JSONField()
    source_sha256 = models.CharField(max_length=64)
    editorial_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["answer", "ordinal"], name="citation_answer_ordinal"),
            models.UniqueConstraint(fields=["answer", "heading"], name="citation_answer_heading"),
            models.CheckConstraint(
                condition=models.Q(ordinal__gte=1, ordinal__lte=12), name="citation_bounded_ordinal"
            ),
        ]
