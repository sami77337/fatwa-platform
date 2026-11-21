"""Append-only, case-scoped synthetic evaluation versions and human decisions."""

import uuid

from django.db import models
from django.db.models import Q

from apps.canonical_search.models import GovernedRecord


class EvaluationRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    engine = models.CharField(max_length=20, default="TITLE_WORDS")
    number = models.PositiveIntegerField()
    corpus = models.JSONField()
    judgements = models.JSONField()
    corpus_sha256 = models.CharField(max_length=64)
    judgements_sha256 = models.CharField(max_length=64)
    ranker_version = models.CharField(max_length=160)
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "engine", "number"], name="ase_case_engine_number"
            ),
            models.CheckConstraint(
                condition=Q(engine__in=["TITLE_WORDS", "CANONICAL_FTS"]), name="ase_engine_kind"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="ase_version_bound"
            ),
        ]


class EvaluationDecision(models.Model):
    revision = models.OneToOneField(
        EvaluationRevision, on_delete=models.PROTECT, related_name="decision"
    )
    action = models.CharField(max_length=8)
    reviews = models.JSONField()
    note = models.CharField(max_length=1000)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=["APPROVE", "REJECT"]), name="ase_decision_kind"
            )
        ]


class CanonicalBenchmarkRun(GovernedRecord):
    revision = models.ForeignKey(EvaluationRevision, on_delete=models.PROTECT)
    judgement_decision = models.ForeignKey(EvaluationDecision, on_delete=models.PROTECT)
    dictionary = models.ForeignKey("canonical_search.SynonymRevision", on_delete=models.PROTECT)
    dictionary_approval = models.ForeignKey(
        "canonical_search.SynonymDecision", on_delete=models.PROTECT
    )
    source_pin = models.JSONField()
    code_pin = models.JSONField()
    comparisons = models.JSONField()
    metrics = models.JSONField()
    workload = models.JSONField()
    regression_status = models.CharField(max_length=8)
    regressions = models.JSONField()
    note = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"], name="ase_run_request"
            ),
            models.CheckConstraint(
                condition=Q(regression_status__in=["CLEAR", "HOLD"]), name="ase_run_status"
            ),
        ]


class CanonicalBenchmarkDecision(GovernedRecord):
    run = models.OneToOneField(CanonicalBenchmarkRun, on_delete=models.PROTECT)
    action = models.CharField(max_length=8)
    note = models.CharField(max_length=1000)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "provider_id", "subject_id", "request_key"],
                name="ase_run_review_request",
            ),
            models.CheckConstraint(
                condition=Q(action__in=["ACCEPT", "HOLD"]), name="ase_run_review_kind"
            ),
        ]
