"""Exact material identities and append-only, case-scoped development rights decisions."""

import uuid

from django.db import models
from django.db.models import Q


class SourceVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    heading = models.OneToOneField(
        "reference.ReferenceHeading", null=True, on_delete=models.PROTECT
    )
    transcript = models.OneToOneField(
        "transcript_case_links.TranscriptLink", null=True, on_delete=models.PROTECT
    )
    kind = models.CharField(max_length=24)
    snapshot = models.JSONField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="TOC_METADATA", heading__isnull=False, transcript__isnull=True)
                    | Q(kind="PRIVATE_TRANSCRIPT", heading__isnull=True, transcript__isnull=False)
                ),
                name="sr_exact_material_kind",
            )
        ]


class RightsRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    uses = models.JSONField(default=list)
    basis = models.CharField(max_length=1000)
    note = models.CharField(max_length=1000)
    valid_until = models.DateTimeField()
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "case", "number"], name="sr_case_source_number"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="sr_revision_bound"
            ),
        ]


class RightsAction(models.Model):
    revision = models.ForeignKey(RightsRevision, related_name="actions", on_delete=models.PROTECT)
    action = models.CharField(max_length=12)
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "action"], name="sr_action_once"),
            models.CheckConstraint(
                condition=Q(action__in=["APPROVE", "REJECT", "REVOKE"]), name="sr_action_kind"
            ),
        ]


class SourceRegistration(models.Model):
    source = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "case"], name="sr_registration_once")
        ]
