"""Stable identities, immutable versions and explicit human review decisions."""

import uuid

from django.db import models
from django.db.models import Q

KINDS = ("RELATED", "REFERRED_BY_SHEIKH", "DUPLICATE_OF", "SUPERSEDES")
ZERO_HASH = "0" * 64


class SealedRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command_id = models.UUIDField(unique=True)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    canonical_payload = models.TextField()
    sha256 = models.CharField(max_length=64)
    transaction_id = models.BigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class LessonCategory(SealedRow):
    """Independent lesson classification; never a Sharia taxonomy reference."""

    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    label = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "label"], name="sl_category_label"),
        ]


class LessonSeries(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class SeriesVersion(SealedRow):
    series = models.ForeignKey(LessonSeries, related_name="versions", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    previous_sha256 = models.CharField(max_length=64, default=ZERO_HASH)
    title = models.CharField(max_length=200)
    teachers = models.JSONField(default=list)
    lesson_order = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="sl_series_version"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=128), name="sl_series_bound"
            ),
        ]


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    series = models.ForeignKey(LessonSeries, related_name="lessons", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class LessonVersion(SealedRow):
    lesson = models.ForeignKey(Lesson, related_name="versions", on_delete=models.PROTECT)
    series_version = models.ForeignKey(SeriesVersion, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    previous_sha256 = models.CharField(max_length=64, default=ZERO_HASH)
    title = models.CharField(max_length=200)
    category = models.ForeignKey(LessonCategory, on_delete=models.PROTECT)
    source_part = models.ForeignKey("answer_media.AnswerPart", null=True, on_delete=models.PROTECT)
    source_snapshot = models.JSONField(default=dict)
    provenance = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lesson", "number"], name="sl_lesson_version"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=128), name="sl_lesson_bound"
            ),
        ]


class CaseRelation(SealedRow):
    source_case = models.ForeignKey(
        "casework.Case", related_name="outgoing_relations", on_delete=models.PROTECT
    )
    source_answer = models.ForeignKey(
        "casework.AnswerRevision", related_name="outgoing_relations", on_delete=models.PROTECT
    )
    target_case = models.ForeignKey(
        "casework.Case", related_name="incoming_relations", on_delete=models.PROTECT
    )
    target_answer = models.ForeignKey(
        "casework.AnswerRevision", related_name="incoming_relations", on_delete=models.PROTECT
    )
    target_case_revision = models.PositiveIntegerField()
    target_evidence_version = models.PositiveIntegerField()
    source_answer_sha256 = models.CharField(max_length=64)
    target_answer_sha256 = models.CharField(max_length=64)
    kind = models.CharField(max_length=24)
    reason = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="sl_relation_kind"),
            models.CheckConstraint(
                condition=~Q(source_case=models.F("target_case")), name="sl_relation_distinct"
            ),
        ]


class CaseLessonLink(SealedRow):
    case = models.ForeignKey("casework.Case", related_name="lesson_links", on_delete=models.PROTECT)
    answer = models.ForeignKey("casework.AnswerRevision", on_delete=models.PROTECT)
    answer_sha256 = models.CharField(max_length=64)
    lesson_version = models.ForeignKey(
        LessonVersion, related_name="case_links", on_delete=models.PROTECT
    )
    target_case_revision = models.PositiveIntegerField()
    target_evidence_version = models.PositiveIntegerField()
    start_ms = models.PositiveIntegerField(null=True)
    end_ms = models.PositiveIntegerField(null=True)
    reason = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(start_ms__isnull=True, end_ms__isnull=True)
                | (
                    Q(start_ms__isnull=False)
                    & (Q(end_ms__isnull=True) | Q(end_ms__gt=models.F("start_ms")))
                ),
                name="sl_lesson_span",
            ),
        ]


class LinkDecision(SealedRow):
    relation = models.ForeignKey(
        CaseRelation, null=True, related_name="decisions", on_delete=models.PROTECT
    )
    lesson_link = models.ForeignKey(
        CaseLessonLink, null=True, related_name="decisions", on_delete=models.PROTECT
    )
    sequence = models.PositiveSmallIntegerField()
    previous_sha256 = models.CharField(max_length=64)
    target_case_revision = models.PositiveIntegerField()
    target_evidence_version = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    note = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(relation__isnull=False, lesson_link__isnull=True)
                | Q(relation__isnull=True, lesson_link__isnull=False),
                name="sl_decision_target",
            ),
            models.UniqueConstraint(fields=["relation", "sequence"], name="sl_relation_decision"),
            models.UniqueConstraint(fields=["lesson_link", "sequence"], name="sl_lesson_decision"),
            models.CheckConstraint(
                condition=Q(action__in=("APPROVE", "REJECT", "WITHDRAW")), name="sl_decision_action"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=2), name="sl_decision_sequence"
            ),
        ]
