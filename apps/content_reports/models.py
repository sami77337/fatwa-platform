"""Immutable submissions and append-only human review history."""

import uuid

from django.db import models
from django.db.models import Q


class ContentReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    reporter_kind = models.CharField(max_length=12)
    reporter_binding = models.CharField(max_length=64)
    request_key = models.UUIDField()
    target = models.JSONField()
    target_sha256 = models.CharField(max_length=64)
    reason = models.CharField(max_length=24)
    description = models.TextField()
    evidence_note = models.TextField(blank=True)
    payload_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "reporter_binding", "request_key"], name="cr_request_once"
            ),
            models.CheckConstraint(
                condition=Q(reporter_kind__in=("REQUESTER", "STAFF")), name="cr_reporter_kind"
            ),
            models.CheckConstraint(
                condition=Q(reason__in=("BROKEN_LINK", "BROKEN_MEDIA", "CONTENT_ERROR", "OTHER")),
                name="cr_reason",
            ),
            models.CheckConstraint(
                condition=Q(case_revision__gte=1, evidence_version__gte=1), name="cr_case_versions"
            ),
            models.CheckConstraint(
                condition=Q(target_sha256__regex=r"^[a-f0-9]{64}$")
                & Q(payload_sha256__regex=r"^[a-f0-9]{64}$")
                & Q(reporter_binding__regex=r"^[a-f0-9]{64}$"),
                name="cr_digests",
            ),
        ]


class ReportEvent(models.Model):
    report = models.ForeignKey(ContentReport, on_delete=models.PROTECT, related_name="events")
    sequence = models.PositiveSmallIntegerField()
    request_key = models.UUIDField()
    action = models.CharField(max_length=12)
    state = models.CharField(max_length=12)
    action_note = models.TextField(blank=True)
    verification_note = models.TextField(blank=True)
    related_report = models.ForeignKey(ContentReport, on_delete=models.PROTECT, null=True)
    subject_id = models.CharField(max_length=128, blank=True)
    provider_id = models.CharField(max_length=128, blank=True)
    auth_epoch = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["report", "sequence"], name="cr_event_sequence"),
            models.UniqueConstraint(fields=["report", "request_key"], name="cr_event_request"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=64), name="cr_event_bound"
            ),
            models.CheckConstraint(
                condition=Q(state__in=("OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED")),
                name="cr_event_state",
            ),
            models.CheckConstraint(
                condition=Q(action__in=("SUBMIT", "START", "RESOLVE", "DISMISS", "REOPEN", "LINK")),
                name="cr_event_action",
            ),
        ]
