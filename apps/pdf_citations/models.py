"""Immutable physical PDF page locators and explicit human printed-label mapping: the canonical media applications retain every byte."""

import uuid

from django.db import models
from django.db.models import F, Q


class PdfCitation(models.Model):
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
    page_number = models.PositiveSmallIntegerField()
    page_count = models.PositiveSmallIntegerField()
    printed_label = models.CharField(max_length=40, blank=True)
    printed_confirmed = models.BooleanField(default=False)
    reason = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="pc_series_number"),
            models.CheckConstraint(condition=Q(number__gte=1, number__lte=64), name="pc_number"),
            models.CheckConstraint(
                condition=Q(
                    page_number__gte=1, page_number__lte=F("page_count"), page_count__lte=10
                ),
                name="pc_page",
            ),
            models.CheckConstraint(
                condition=(
                    Q(printed_label="", printed_confirmed=False)
                    | (~Q(printed_label="") & Q(printed_confirmed=True))
                ),
                name="pc_human_label",
            ),
            models.CheckConstraint(
                condition=(
                    Q(attachment__isnull=False, part__isnull=True)
                    | Q(attachment__isnull=True, part__isnull=False)
                ),
                name="pc_exact_owner",
            ),
            models.CheckConstraint(
                condition=Q(snapshot_sha256__regex=r"^[a-f0-9]{64}$"), name="pc_digest"
            ),
        ]


class PdfCitationAction(models.Model):
    citation = models.ForeignKey(PdfCitation, related_name="actions", on_delete=models.PROTECT)
    action = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["citation", "action"], name="pc_action_once"),
            models.CheckConstraint(
                condition=Q(action__in=["CONFIRM", "WITHDRAW"]), name="pc_action_kind"
            ),
        ]
