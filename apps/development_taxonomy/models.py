"""An independent provisional fiqh registry; no source/reference tree mutation."""

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


class DevelopmentTree(Sealed):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    namespace = models.CharField(max_length=32, default="SYNTHETIC_PROVISIONAL_FIQH")
    provenance = models.CharField(max_length=2000)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(namespace="SYNTHETIC_PROVISIONAL_FIQH"), name="dt_provisional_fiqh"
            )
        ]


class Concept(Sealed):
    tree = models.ForeignKey(DevelopmentTree, on_delete=models.PROTECT)
    definition = models.CharField(max_length=1000)


class TreeVersion(Sealed):
    tree = models.ForeignKey(DevelopmentTree, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    previous = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    nodes = models.JSONField()
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tree", "number"), name="dt_tree_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=2048), name="dt_version_bound"
            ),
        ]


class MigrationPlan(Sealed):
    tree = models.ForeignKey(DevelopmentTree, on_delete=models.PROTECT)
    source_version = models.ForeignKey(
        TreeVersion, on_delete=models.PROTECT, related_name="outgoing_plans"
    )
    target_version = models.ForeignKey(
        TreeVersion, on_delete=models.PROTECT, related_name="incoming_plans"
    )
    mapping = models.JSONField()
    manifest = models.JSONField()
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)


class HumanReview(Sealed):
    version = models.OneToOneField(TreeVersion, null=True, on_delete=models.PROTECT)
    plan = models.OneToOneField(MigrationPlan, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=8)
    content_digest = models.CharField(max_length=64)
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(version__isnull=False, plan__isnull=True)
                    | Q(version__isnull=True, plan__isnull=False)
                ),
                name="dt_review_target",
            ),
            models.CheckConstraint(
                condition=Q(action__in=("APPROVE", "REJECT")), name="dt_review_action"
            ),
        ]


class MigrationExecution(Sealed):
    plan = models.ForeignKey(MigrationPlan, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8)
    previous = models.OneToOneField("self", null=True, on_delete=models.PROTECT)
    count = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("plan", "kind"), name="dt_plan_execution"),
            models.CheckConstraint(
                condition=Q(kind__in=("APPLY", "ROLLBACK")), name="dt_execution_kind"
            ),
            models.CheckConstraint(condition=Q(count__lte=32), name="dt_execution_bound"),
        ]


class CaseClassification(Sealed):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    answer = models.ForeignKey("casework.AnswerRevision", on_delete=models.PROTECT)
    evidence_version = models.PositiveIntegerField()
    sequence = models.PositiveIntegerField()
    previous = models.OneToOneField("self", null=True, on_delete=models.PROTECT)
    version = models.ForeignKey(TreeVersion, on_delete=models.PROTECT)
    primary = models.ForeignKey(Concept, on_delete=models.PROTECT)
    additional = models.JSONField(default=list)
    execution = models.ForeignKey(MigrationExecution, null=True, on_delete=models.PROTECT)
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("case", "sequence"), name="dt_case_sequence"),
            models.UniqueConstraint(fields=("case", "execution"), name="dt_case_execution"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=2048), name="dt_binding_bound"
            ),
        ]
