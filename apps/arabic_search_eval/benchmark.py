"""Actual pinned FTS comparisons against authored, independently reviewed judgments.

All records remain synthetic development evidence. No result promotes a search
configuration or grants corpus, publication, specialist, or production approval.
"""

import re
import uuid
from hashlib import sha256
from pathlib import Path

from django.db import connection

from apps.canonical_search import governance
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument, ShadowComparison
from apps.canonical_search.text import PROFILE, digest, query
from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service
from apps.research_workspace import services as workspace

from . import benchmark_policy as policy
from . import review
from .evaluation import score
from .models import (
    CanonicalBenchmarkDecision,
    CanonicalBenchmarkRun,
    EvaluationDecision,
    EvaluationRevision,
)

ENGINE = "CANONICAL_FTS"
VERSION = "canonical-fts-benchmark-v1"
MAX_RECORDS = 64
MAX_QUERIES = 8
MAX_RUNS = 64
METRICS = ("precision_at_5", "recall_at_5", "reciprocal_rank")


def code_pin():
    root = Path(__file__).parent
    files = {
        "canonical_search/text.py": root.parent / "canonical_search/text.py",
        "canonical_search/services.py": root.parent / "canonical_search/services.py",
        "canonical_search/governance.py": root.parent / "canonical_search/governance.py",
        "arabic_search_eval/evaluation.py": root / "evaluation.py",
        "arabic_search_eval/benchmark.py": root / "benchmark.py",
    }
    return {
        "version": VERSION,
        "baseline_profile": PROFILE,
        "scorer": "arabic_search_eval.evaluation.score:k=5",
        "precision_denominator": "returned_top_5_count",
        "ranking_window": 5,
        "observation_window": search.PAGE_SIZE,
        "regression_rule": "per_query_quality_negative_errors_and_5x_or_50ms_total_latency_v1",
        "files": {name: sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
    }


def engine_identity():
    return VERSION + ":" + digest(code_pin())


def _current(case):
    return EvaluationRevision.objects.filter(case=case, engine=ENGINE).order_by("-number").first()


def corpus_in_context(context):
    pin = governance._source_pin(context.search, context.case)
    generation, usable, _ = search._case_data(context.search, context.case)
    if not 1 <= len(usable) <= MAX_RECORDS:
        raise cases.CaseConflict("canonical_benchmark_corpus_bound")
    records = []
    for row in SearchDocument.objects.filter(generation=generation).order_by("ordinal"):
        if str(row.pk) in usable:
            search._verify(row)
            records.append(
                {"id": str(row.pk), "digest": row.digest, "kind": row.kind, "pin": row.pin}
            )
    return {"synthetic_only": True, "source_pin": pin, "records": records}


def validate_judgements(judgements, corpus):
    if type(judgements) is not list or not 1 <= len(judgements) <= MAX_QUERIES:
        raise cases.CaseConflict("canonical_benchmark_queries_bound")
    ids, texts, allowed = set(), set(), {r["id"] for r in corpus["records"]}
    for item in judgements:
        if type(item) is not dict or set(item) != {"id", "query", "expected", "rationale"}:
            raise cases.CaseConflict("canonical_benchmark_judgement_invalid")
        if type(item["id"]) is not str or not re.fullmatch(r"[a-z][a-z0-9._-]{0,39}", item["id"]):
            raise cases.CaseConflict("canonical_benchmark_query_id_invalid")
        query(item["query"], "FTS")
        review._text(item["rationale"])
        expected = item["expected"]
        if (
            item["id"] in ids
            or item["query"] in texts
            or type(expected) is not list
            or len(expected) > MAX_RECORDS
            or any(type(value) is not str for value in expected)
            or len(set(expected)) != len(expected)
            or set(expected) - allowed
        ):
            raise cases.CaseConflict("canonical_benchmark_expected_invalid")
        ids.add(item["id"])
        texts.add(item["query"])
    if not any(item["expected"] for item in judgements):
        raise cases.CaseConflict("canonical_benchmark_positive_judgement_required")
    return judgements


def _suite(context, identifier, *, approved=False):
    row = EvaluationRevision.objects.filter(
        case=context.case, engine=ENGINE, pk=cases._uuid(identifier)
    ).first()
    if row is None:
        raise cases.CaseConflict("canonical_benchmark_suite_unavailable")
    review._verify(row)
    current = _current(context.case)
    if current is None or current.pk != row.pk or row.ranker_version != engine_identity():
        raise cases.CaseConflict("canonical_benchmark_suite_stale")
    if row.corpus != corpus_in_context(context):
        raise cases.CaseConflict("canonical_benchmark_corpus_stale")
    validate_judgements(row.judgements, row.corpus)
    decision = EvaluationDecision.objects.filter(revision=row).first()
    if decision:
        validate_reviews(row, decision.reviews, decision.action)
        if (decision.provider_id, decision.subject_id) == (row.provider_id, row.subject_id):
            raise cases.CaseConflict("independent_evaluation_reviewer_required")
    if approved and (decision is None or decision.action != "APPROVE"):
        raise cases.CaseConflict("canonical_benchmark_judgements_unapproved")
    return row, decision


def validate_reviews(row, reviews, action):
    try:
        ids = {item["id"] for item in row.judgements}
        if (
            type(reviews) is not list
            or len(reviews) != len(ids)
            or {r["id"] for r in reviews} != ids
        ):
            raise ValueError()
        for item in reviews:
            if set(item) != {"id", "verdict", "note"} or item["verdict"] not in {
                "AGREE",
                "DISAGREE",
            }:
                raise ValueError()
            review._text(item["note"])
        if action not in {"APPROVE", "REJECT"} or (
            action == "APPROVE" and any(r["verdict"] != "AGREE" for r in reviews)
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise cases.CaseConflict("evaluation_judgements_required") from exc


@mutation_service
def propose(*, expected_number, expected_corpus_sha256, judgements, note, **base):
    review._text(note)
    if type(expected_number) is not int or not 0 <= expected_number < 64:
        raise cases.CaseConflict("evaluation_version_invalid")
    with policy.boundary(**base, action="PROPOSE") as context:
        context.permit("READ")
        corpus = corpus_in_context(context)
        if workspace._digest(corpus) != expected_corpus_sha256:
            raise cases.CaseConflict("canonical_benchmark_corpus_stale")
        validate_judgements(judgements, corpus)
        previous = _current(context.case)
        if (previous.number if previous else 0) != expected_number:
            raise cases.CaseConflict("evaluation_revision_changed")
        row = EvaluationRevision.objects.create(
            case=context.case,
            engine=ENGINE,
            number=expected_number + 1,
            corpus=corpus,
            judgements=judgements,
            corpus_sha256=workspace._digest(corpus),
            judgements_sha256=workspace._digest(judgements),
            ranker_version=engine_identity(),
            note=note,
            subject_id=context.search.actor.subject_id,
            provider_id=context.search.provider.provider_id,
            auth_epoch=context.search.actor.auth_epoch,
        )
        context.wrote(row)
        return review._data(row)


@mutation_service
def judge(
    *, revision_id, corpus_sha256, judgements_sha256, action, confirmed, reviews, note, **base
):
    review._text(note)
    if confirmed is not True or action not in {"APPROVE", "REJECT"}:
        raise cases.CaseConflict("evaluation_explicit_review_required")
    with policy.boundary(**base, action="JUDGE") as context:
        context.permit("READ")
        row, previous = _suite(context, revision_id)
        if previous is not None or (row.corpus_sha256, row.judgements_sha256) != (
            corpus_sha256,
            judgements_sha256,
        ):
            raise cases.CaseConflict("evaluation_revision_changed")
        if (row.provider_id, row.subject_id) == (
            context.search.provider.provider_id,
            context.search.actor.subject_id,
        ):
            raise cases.CaseConflict("independent_evaluation_reviewer_required")
        validate_reviews(row, reviews, action)
        decision = EvaluationDecision.objects.create(
            revision=row,
            action=action,
            reviews=reviews,
            note=note,
            subject_id=context.search.actor.subject_id,
            provider_id=context.search.provider.provider_id,
            auth_epoch=context.search.actor.auth_epoch,
        )
        context.wrote(decision)
        return review._data(row)


def _metrics(judgements, comparisons):
    rows, regressions = [], []
    for judgement, comparison in zip(judgements, comparisons, strict=True):
        baseline = [r["document_id"] for r in comparison["baseline"]["rows"]]
        candidate = [r["document_id"] for r in comparison["candidate"].get("rows", [])]
        before, after = (
            score(judgement["expected"], baseline),
            score(judgement["expected"], candidate),
        )
        row = {
            "id": judgement["id"],
            "query": judgement["query"],
            "expected": judgement["expected"],
            "comparison_id": comparison["id"],
            "comparison_digest": comparison["digest"],
            "baseline": baseline,
            "candidate": candidate,
            "baseline_score": before,
            "candidate_score": after,
            "candidate_status": comparison["candidate_status"],
            "baseline_ms": comparison["baseline_ms"],
            "candidate_ms": comparison["candidate_ms"],
        }
        rows.append(row)
        if comparison["candidate_status"] != "OK":
            regressions.append({"id": judgement["id"], "reason": "candidate_error"})
        for name in METRICS:
            if before[name] is not None and after[name] < before[name]:
                regressions.append(
                    {
                        "id": judgement["id"],
                        "reason": name,
                        "baseline": before[name],
                        "candidate": after[name],
                    }
                )
        if not judgement["expected"] and len(candidate) > len(baseline):
            regressions.append(
                {
                    "id": judgement["id"],
                    "reason": "negative_false_positives",
                    "baseline": len(baseline),
                    "candidate": len(candidate),
                }
            )
    positives = [r for r in rows if r["expected"]]
    negatives = [r for r in rows if not r["expected"]]
    summaries = {}
    for name in ("baseline", "candidate"):
        summaries[name] = {
            metric: sum(r[f"{name}_score"][metric] for r in positives) / len(positives)
            for metric in METRICS
        }
        summaries[name].update(
            judged_query_hit_coverage_at_5=sum(
                r[f"{name}_score"]["recall_at_5"] > 0 for r in positives
            )
            / len(positives),
            negative_false_positive_queries=sum(bool(r[name]) for r in negatives),
            negative_returned_documents=sum(len(r[name]) for r in negatives),
            exact_order_queries=sum(r[f"{name}_score"]["exact_order"] for r in rows),
            total_ms=sum(r[f"{name}_ms"] for r in rows),
        )
    latency_budget = max(50, 5 * summaries["baseline"]["total_ms"])
    if summaries["candidate"]["total_ms"] > latency_budget:
        regressions.append(
            {
                "id": "all",
                "reason": "latency_budget_ms",
                "baseline": latency_budget,
                "candidate": summaries["candidate"]["total_ms"],
            }
        )
    return {
        "queries": rows,
        "summary": summaries,
        "counts": {
            "queries": len(rows),
            "positive": len(positives),
            "negative": len(negatives),
            "candidate_errors": sum(r["candidate_status"] != "OK" for r in rows),
        },
        "candidate_latency_budget_ms": latency_budget,
        "precision_denominator": "returned_top_5_count",
        "synthetic_only": True,
    }, regressions


class QueryCounter:
    def __init__(self):
        self.statements = 0
        self.selects = 0

    def __call__(self, execute, sql, params, many, context):
        self.statements += 1
        self.selects += sql.lstrip().upper().startswith(("SELECT", "WITH"))
        return execute(sql, params, many, context)


def _run(context, identifier):
    row = (
        CanonicalBenchmarkRun.objects.select_related(
            "revision", "judgement_decision", "dictionary", "dictionary_approval"
        )
        .filter(case=context.case, pk=cases._uuid(identifier))
        .first()
    )
    if row is None:
        raise cases.CaseConflict("canonical_benchmark_run_unavailable")
    search._verify(row)
    revision, decision = _suite(context, row.revision_id, approved=True)
    if (
        decision.pk != row.judgement_decision_id
        or row.source_pin != revision.corpus["source_pin"]
        or row.code_pin != code_pin()
    ):
        raise cases.CaseConflict("canonical_benchmark_run_stale")
    context.search.require(context.case, "DICTIONARY_USE")
    dictionary = governance._revision(context.search, context.case, row.dictionary_id)
    approval = governance._approved(context.search, dictionary)
    if approval.pk != row.dictionary_approval_id:
        raise cases.CaseConflict("canonical_benchmark_dictionary_stale")
    comparisons = []
    for judgement, pin in zip(revision.judgements, row.comparisons, strict=True):
        observed = governance.shadow_in_context(
            context.search, case=context.case, comparison_id=pin["id"]
        )
        if (
            observed["digest"] != pin["digest"]
            or observed["query"] != judgement["query"]
            or observed["dictionary_id"] != str(dictionary.pk)
        ):
            raise cases.CaseConflict("canonical_benchmark_comparison_changed")
        comparisons.append(observed)
    metrics, regressions = _metrics(revision.judgements, comparisons)
    if (
        row.metrics != metrics
        or row.regressions != regressions
        or row.regression_status != ("HOLD" if regressions else "CLEAR")
    ):
        raise cases.CaseConflict("canonical_benchmark_metrics_changed")
    return row, comparisons


def _data(context, row, comparisons):
    decision = CanonicalBenchmarkDecision.objects.filter(run=row).first()
    if decision:
        search._verify(decision)
    return {
        "id": str(row.pk),
        "digest": row.digest,
        "revision_id": str(row.revision_id),
        "judgements_sha256": row.revision.judgements_sha256,
        "corpus_sha256": row.revision.corpus_sha256,
        "suite_number": row.revision.number,
        "dictionary_id": str(row.dictionary_id),
        "dictionary_digest": row.dictionary.digest,
        "source_pin": row.source_pin,
        "code_pin": row.code_pin,
        "metrics": row.metrics,
        "workload": row.workload,
        "regression_status": row.regression_status,
        "regressions": row.regressions,
        "comparisons": comparisons,
        "created_at": row.created_at,
        "author": row.subject_id,
        "note": row.note,
        "review": None
        if decision is None
        else {
            "action": decision.action,
            "note": decision.note,
            "reviewer": decision.subject_id,
            "digest": decision.digest,
            "created_at": decision.created_at,
        },
        "synthetic_only": True,
        "promotion_performed": False,
    }


def read_in_context(context, *, run_id):
    context.permit("READ")
    row, comparisons = _run(context, run_id)
    return _data(context, row, comparisons)


@mutation_service
def read(*, run_id, **base):
    with policy.boundary(**base, action="READ") as context:
        return read_in_context(context, run_id=run_id)


@mutation_service
def run(
    *,
    revision_id,
    dictionary_id,
    expected_corpus_sha256,
    expected_judgements_sha256,
    expected_dictionary_digest,
    request_key,
    note,
    **base,
):
    review._text(note)
    with policy.boundary(**base, action="RUN") as context:
        revision, judgement_decision = _suite(context, revision_id, approved=True)
        dictionary = governance._revision(context.search, context.case, dictionary_id)
        approval = governance._approved(context.search, dictionary)
        if (
            revision.corpus_sha256 != expected_corpus_sha256
            or revision.judgements_sha256 != expected_judgements_sha256
            or dictionary.digest != expected_dictionary_digest
        ):
            raise cases.CaseConflict("canonical_benchmark_inputs_changed")
        request_key = cases._uuid(request_key)
        existing = CanonicalBenchmarkRun.objects.filter(
            case=context.case,
            provider_id=context.search.provider.provider_id,
            subject_id=context.search.actor.subject_id,
            request_key=request_key,
        ).first()
        if existing:
            if (
                existing.revision_id != revision.pk
                or existing.dictionary_id != dictionary.pk
                or existing.note != note
            ):
                raise cases.CaseConflict("canonical_benchmark_request_conflict")
            return read_in_context(context, run_id=existing.pk)
        if CanonicalBenchmarkRun.objects.filter(case=context.case).count() >= MAX_RUNS:
            raise cases.CaseConflict("canonical_benchmark_run_bound")
        if (
            ShadowComparison.objects.filter(case=context.case).count() + len(revision.judgements)
            > governance.MAX_SHADOWS
        ):
            raise cases.CaseConflict("search_shadow_history_bound")
        comparisons, counter = [], QueryCounter()
        with connection.execute_wrapper(counter):
            for item in revision.judgements:
                result = governance.run_shadow_in_context(
                    context.search,
                    case=context.case,
                    revision_id=dictionary.pk,
                    value=item["query"],
                    expected_revision=context.case.revision,
                    expected_evidence_version=context.case.evidence_version,
                    request_key=uuid.uuid5(request_key, item["id"]),
                )
                comparisons.append(result["comparison"])
        metrics, regressions = _metrics(revision.judgements, comparisons)
        row = search._seal(
            CanonicalBenchmarkRun(
                **governance._identity(context.search, context.case, request_key),
                revision=revision,
                judgement_decision=judgement_decision,
                dictionary=dictionary,
                dictionary_approval=approval,
                source_pin=revision.corpus["source_pin"],
                code_pin=code_pin(),
                comparisons=[{"id": c["id"], "digest": c["digest"]} for c in comparisons],
                metrics=metrics,
                regressions=regressions,
                regression_status="HOLD" if regressions else "CLEAR",
                workload={
                    "query_pairs": len(comparisons),
                    "sql_statements": counter.statements,
                    "sql_selects": counter.selects,
                    "count_scope": "shadow_execution_and_source_checks_only",
                    "external_ai_calls": 0,
                    "monetary_cost": None,
                    "cost_status": "LOCAL_DATABASE_CURRENCY_COST_NOT_MEASURED",
                },
                note=note,
            )
        )
        context.wrote(row)
        context.permit("READ")
        return _data(context, row, comparisons)


@mutation_service
def decide(*, run_id, expected_digest, action, confirmed, note, request_key, **base):
    review._text(note)
    if action not in {"ACCEPT", "HOLD"} or confirmed is not True:
        raise cases.CaseConflict("canonical_benchmark_explicit_review_required")
    with policy.boundary(**base, action="REVIEW") as context:
        row, comparisons = _run(context, run_id)
        if (
            row.digest != expected_digest
            or CanonicalBenchmarkDecision.objects.filter(run=row).exists()
        ):
            raise cases.CaseConflict("canonical_benchmark_review_changed")
        actor = (context.search.provider.provider_id, context.search.actor.subject_id)
        if actor in {
            (row.provider_id, row.subject_id),
            (row.revision.provider_id, row.revision.subject_id),
        }:
            raise cases.CaseConflict("canonical_benchmark_independent_reviewer_required")
        if action == "ACCEPT" and row.regression_status != "CLEAR":
            raise cases.CaseConflict("canonical_benchmark_regressions_require_hold")
        decision = search._seal(
            CanonicalBenchmarkDecision(
                **governance._identity(context.search, context.case, request_key),
                run=row,
                action=action,
                note=note,
            )
        )
        context.wrote(decision)
        context.permit("READ")
        return _data(context, row, comparisons)


def desk_in_context(context):
    context.permit("READ")
    corpus = corpus_in_context(context)
    row = _current(context.case)
    current = review._data(row) if row else None
    if current:
        available = row.corpus == corpus and row.ranker_version == engine_identity()
        if not available:
            current = {key: current[key] for key in ("id", "number", "state")}
        current["current"] = available
    # History is metadata only until the exact run's current source guards pass.
    history = [
        {
            "id": str(r.pk),
            "digest": r.digest,
            "created_at": r.created_at,
            "suite_number": r.revision.number,
        }
        for r in CanonicalBenchmarkRun.objects.filter(case=context.case)
        .select_related("revision")
        .order_by("-created_at", "-pk")
    ]
    return {
        "case_ref": context.case.public_ref,
        "corpus": corpus,
        "corpus_sha256": workspace._digest(corpus),
        "current": current,
        "current_number": row.number if row else 0,
        "runs": history,
        "synthetic_only": True,
    }


@mutation_service
def desk(**base):
    with policy.boundary(**base, action="READ") as context:
        return desk_in_context(context)
