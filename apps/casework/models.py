"""Durable synthetic cases. Original sources and authored versions are immutable."""

import uuid

from django.db import models
from django.db.models import Q

STAGES = ("RECEIVED", "UNDER_REVIEW", "NEEDS_CLARIFICATION", "RETURNED_FOR_CHANGES", "ANSWERED")


class Case(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_ref = models.CharField(max_length=40, unique=True, editable=False)
    requester_id = models.CharField(max_length=128, editable=False)
    idempotency_key = models.CharField(max_length=128, editable=False)
    intake_sha256 = models.CharField(max_length=64, editable=False)
    tracking = models.OneToOneField(
        "delivery_queue.RequesterTrackingCase",
        on_delete=models.PROTECT,
        related_name="durable_case",
    )
    stage = models.CharField(max_length=32, default="RECEIVED")
    revision = models.PositiveIntegerField(default=1)
    evidence_version = models.PositiveIntegerField(default=1)
    answer_revision = models.PositiveIntegerField(default=0)
    approved_answer = models.ForeignKey(
        "AnswerRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_for_cases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requester_id", "idempotency_key"], name="cw_case_request_key"
            ),
            models.CheckConstraint(condition=Q(stage__in=STAGES), name="cw_case_stage"),
            models.CheckConstraint(
                condition=Q(revision__gte=1, evidence_version__gte=1), name="cw_case_versions"
            ),
            models.CheckConstraint(
                condition=Q(public_ref__regex=r"^FT-[0-9]{4}-[A-F0-9]{20}$"),
                name="cw_case_public_ref",
            ),
            models.CheckConstraint(
                condition=Q(intake_sha256__regex=r"^[a-f0-9]{64}$"), name="cw_case_intake_digest"
            ),
            models.CheckConstraint(
                condition=(
                    Q(stage="ANSWERED", approved_answer__isnull=False)
                    | (~Q(stage="ANSWERED") & Q(approved_answer__isnull=True))
                ),
                name="cw_case_approval_state",
            ),
        ]


class CaseSource(models.Model):
    case = models.OneToOneField(
        Case, primary_key=True, on_delete=models.PROTECT, related_name="source"
    )
    channel = models.CharField(max_length=20, default="WEBSITE")
    source_event_id = models.CharField(max_length=128, unique=True)
    original_question = models.TextField()
    question_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(channel="WEBSITE"), name="cw_source_channel"),
            models.CheckConstraint(
                condition=Q(original_question__regex=r"\S"), name="cw_source_nonempty"
            ),
            models.CheckConstraint(
                condition=Q(question_sha256__regex=r"^[a-f0-9]{64}$"), name="cw_source_digest"
            ),
        ]


class CaseEvidence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="evidence")
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=16)
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "version"], name="cw_evidence_version"),
            models.CheckConstraint(condition=Q(version__gte=1), name="cw_evidence_positive"),
            models.CheckConstraint(
                condition=(Q(version=1, kind="ORIGINAL") | Q(version__gt=1, kind="FOLLOWUP")),
                name="cw_evidence_kind",
            ),
        ]


class AnswerRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="answers")
    revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "revision"], name="cw_answer_revision"),
            models.CheckConstraint(
                condition=Q(revision__gte=1, evidence_version__gte=1), name="cw_answer_versions"
            ),
        ]


class CaseDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="decisions")
    answer = models.OneToOneField(AnswerRevision, on_delete=models.PROTECT, related_name="decision")
    evidence_version = models.PositiveIntegerField()
    action = models.CharField(max_length=24)
    note = models.TextField(blank=True)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=("APPROVE", "RETURN_FOR_CHANGES")), name="cw_decision_action"
            )
        ]


class CaseEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="events")
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    stage = models.CharField(max_length=32)
    evidence_version = models.PositiveIntegerField()
    answer_revision = models.PositiveIntegerField()
    subject_id = models.CharField(max_length=128)
    note = models.TextField(blank=True)
    answer = models.ForeignKey(AnswerRevision, null=True, blank=True, on_delete=models.PROTECT)
    decision = models.OneToOneField(CaseDecision, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["case", "sequence"], name="cw_event_sequence"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, evidence_version__gte=1), name="cw_event_versions"
            ),
            models.CheckConstraint(condition=Q(stage__in=STAGES), name="cw_event_stage"),
            models.CheckConstraint(
                condition=Q(
                    action__in=(
                        "INTAKE",
                        "FOLLOWUP",
                        "SAVE_ANSWER",
                        "CLARIFICATION",
                        "APPROVE",
                        "RETURN_FOR_CHANGES",
                        "ROTATE_ACCESS",
                        "REVOKE_ACCESS",
                    )
                ),
                name="cw_event_action",
            ),
        ]
