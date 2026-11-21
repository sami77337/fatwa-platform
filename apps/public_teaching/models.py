import uuid

from django.db import models
from django.db.models import Q

KINDS = ("SCHOLAR_MATERIAL", "LESSON", "SERIES")


class TeachingItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    kind = models.CharField(max_length=24)
    external_id = models.UUIDField()
    secondary_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="pt_item_kind"),
            models.UniqueConstraint(
                fields=("kind", "external_id", "secondary_id"),
                nulls_distinct=False,
                name="pt_stable_identity",
            ),
        ]


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    request_key = models.UUIDField(unique=True)
    request_sha256 = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    note = models.CharField(max_length=1000)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class TeachingVersion(Sealed):
    item = models.ForeignKey(TeachingItem, related_name="versions", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    previous_digest = models.CharField(max_length=64, default="0" * 64)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=2000, blank=True)
    topic = models.CharField(max_length=160, blank=True)
    teacher_labels = models.JSONField(default=list)
    attribution = models.CharField(max_length=1000, blank=True)
    profile = models.ForeignKey(
        "public_knowledge.PublicRevision",
        null=True,
        related_name="teaching_attributions",
        on_delete=models.PROTECT,
    )
    library_version = models.ForeignKey(
        "research_library.LibraryVersion", null=True, on_delete=models.PROTECT
    )
    lesson_metadata = models.ForeignKey(
        "public_knowledge.PublicRevision",
        null=True,
        related_name="teaching_readers",
        on_delete=models.PROTECT,
    )
    lesson_version = models.ForeignKey(
        "scholarly_links.LessonVersion", null=True, on_delete=models.PROTECT
    )
    series_version = models.ForeignKey(
        "scholarly_links.SeriesVersion", null=True, on_delete=models.PROTECT
    )
    source_pins = models.JSONField(default=dict)
    members = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("item", "number"), name="pt_version_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="pt_version_bound"
            ),
        ]


class TeachingAction(Sealed):
    version = models.ForeignKey(TeachingVersion, related_name="actions", on_delete=models.PROTECT)
    sequence = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    action = models.CharField(max_length=16)
    valid_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("version", "sequence"), name="pt_action_sequence"),
            models.UniqueConstraint(fields=("version", "action"), name="pt_action_once"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=4), name="pt_action_bound"
            ),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "APPROVE", "RELEASE", "WITHDRAW")),
                name="pt_action_kind",
            ),
            models.CheckConstraint(
                condition=Q(action="RELEASE", valid_until__isnull=False)
                | (~Q(action="RELEASE") & Q(valid_until__isnull=True)),
                name="pt_action_deadline",
            ),
        ]
