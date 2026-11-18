"""Versioned locators only: the canonical media applications retain every byte."""

import uuid

from django.db import models
from django.db.models import F, Q


class TimedCitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.UUIDField(default=uuid.uuid4)
    number = models.PositiveSmallIntegerField()
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    answer = models.ForeignKey("casework.AnswerRevision", on_delete=models.PROTECT)
    attachment = models.ForeignKey(
        "case_attachments.CaseAttachment", null=True, on_delete=models.PROTECT
    )
    part = models.ForeignKey("answer_media.AnswerPart", null=True, on_delete=models.PROTECT)
    previous = models.OneToOneField("self", null=True, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()
    duration_ms = models.PositiveIntegerField()
    reason = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="tc_series_number"),
            models.CheckConstraint(condition=Q(number__gte=1, number__lte=64), name="tc_number"),
            models.CheckConstraint(
                condition=Q(
                    start_ms__lt=F("end_ms"), end_ms__lte=F("duration_ms"), duration_ms__lte=120000
                ),
                name="tc_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(attachment__isnull=False, part__isnull=True)
                    | Q(attachment__isnull=True, part__isnull=False)
                ),
                name="tc_exact_owner",
            ),
            models.CheckConstraint(
                condition=Q(snapshot_sha256__regex=r"^[a-f0-9]{64}$"), name="tc_digest"
            ),
        ]


class TimedCitationAction(models.Model):
    citation = models.ForeignKey(TimedCitation, related_name="actions", on_delete=models.PROTECT)
    action = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["citation", "action"], name="tc_action_once"),
            models.CheckConstraint(
                condition=Q(action__in=["CONFIRM", "WITHDRAW"]), name="tc_action_kind"
            ),
        ]
