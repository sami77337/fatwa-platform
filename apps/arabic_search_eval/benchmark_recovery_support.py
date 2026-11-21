"""Nonempty durable benchmark records reopened with fresh current trust only."""

import uuid
from contextlib import contextmanager
from dataclasses import replace

from django.test import override_settings

from apps.canonical_search import governance_recovery_support
from apps.canonical_search import services as search
from apps.canonical_search.governance_test_support import TERM
from apps.casework import services as cases
from apps.mufti_review.identity import IdentityUnavailable
from apps.research_workspace import services as workspace

from . import benchmark, review
from .benchmark_policy import MODELS
from .benchmark_test_support import BenchmarkAuthority
from .models import EvaluationRevision
from .views import proposed_bundle

TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("ase_revision_guard", "ase_decision_guard", "ase_canonical_benchmark_insert")
TRIGGERS = (
    "ase_revision_guard",
    "ase_decision_guard",
    "ase_canonical_run_insert",
    "ase_canonical_run_immutable",
    "ase_canonical_review_insert",
    "ase_canonical_review_immutable",
)


@contextmanager
def configuration(pins):
    with governance_recovery_support.configuration(pins) as base:
        authority = BenchmarkAuthority(pins["public_ref"])
        with override_settings(
            FATWA_CANONICAL_BENCHMARK_ENABLED=True, FATWA_CANONICAL_BENCHMARK_AUTHORITY=authority
        ):
            yield base, authority


def _history(case_id):
    result = {}
    for model in MODELS:
        query = model.objects.filter(
            **{
                "revision__case_id"
                if model._meta.model_name == "evaluationdecision"
                else "case_id": case_id
            }
        )
        result[model._meta.db_table] = [search._body(row) for row in query.order_by("pk")]
    return result


def populate():
    pins = governance_recovery_support.populate()
    with configuration(pins) as (base, _):
        desk = benchmark.desk(**base)
        document = desk["corpus"]["records"][0]["id"]
        judgements = [
            {
                "id": "alias",
                "query": TERM,
                "expected": [document],
                "rationale": "An authored synthetic synonym query should reach this question.",
            },
            {
                "id": "plain",
                "query": "المعاملات",
                "expected": [document],
                "rationale": "Authored exact synthetic source word.",
            },
            {
                "id": "negative",
                "query": "غياباصطناعي",
                "expected": [],
                "rationale": "Authored negative synthetic control.",
            },
        ]
        suite = benchmark.propose(
            **base,
            expected_number=0,
            expected_corpus_sha256=desk["corpus_sha256"],
            judgements=judgements,
            note="Restore fixture with independently authored synthetic expectations.",
        )
        benchmark.judge(
            **{**base, "subject_id": "publisher"},
            revision_id=suite["id"],
            corpus_sha256=suite["corpus_sha256"],
            judgements_sha256=suite["judgements_sha256"],
            action="APPROVE",
            confirmed=True,
            reviews=[
                {
                    "id": item["id"],
                    "verdict": "AGREE",
                    "note": "Synthetic independent reviewer fixture only.",
                }
                for item in judgements
            ],
            note="This does not constitute specialist gold-corpus review.",
        )
        result = benchmark.run(
            **base,
            revision_id=suite["id"],
            dictionary_id=pins["dictionary_id"],
            expected_corpus_sha256=suite["corpus_sha256"],
            expected_judgements_sha256=suite["judgements_sha256"],
            expected_dictionary_digest=pins["dictionary_digest"],
            request_key=uuid.uuid4(),
            note="Actual restored benchmark verification fixture.",
        )
        benchmark.decide(
            **{**base, "subject_id": "publisher"},
            run_id=result["id"],
            expected_digest=result["digest"],
            action="ACCEPT",
            confirmed=True,
            note="Independent decision for the exact synthetic run, no promotion.",
            request_key=uuid.uuid4(),
        )
        # A simultaneous legacy fixture remains its original TITLE_WORDS engine,
        # corpus semantics and PENDING state; its version number is independent.
        bundle = proposed_bundle()
        bundle["queries"] = bundle["queries"][:2]
        from .test_review import Authority

        with override_settings(
            FATWA_ARABIC_SEARCH_REVIEW_ENABLED=True,
            FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY=Authority(pins["public_ref"]),
        ):
            title = review.propose(
                **base,
                expected_number=0,
                bundle=bundle,
                note="Preserved original title-word fixture, review still pending.",
            )
        pins.update(
            benchmark_run_id=result["id"],
            benchmark_run_digest=result["digest"],
            benchmark_metrics=result["metrics"],
            benchmark_suite_id=suite["id"],
            benchmark_judgements_sha256=suite["judgements_sha256"],
            title_suite_id=title["id"],
            title_corpus_sha256=title["corpus_sha256"],
            benchmark_history=_history(pins["case_id"]),
        )
    return pins


def verify_restored(pins):
    initial = _history(pins["case_id"])
    assert initial == pins["benchmark_history"]
    denials = {}
    with configuration(pins) as (base, authority):

        def read():
            return benchmark.read(**base, run_id=pins["benchmark_run_id"])

        def desk():
            return benchmark.desk(**base)

        def denied(name):
            count = 0
            for operation in (read, desk):
                try:
                    operation()
                except (cases.CaseConflict, IdentityUnavailable):
                    count += 1
                else:
                    raise AssertionError(f"Restored benchmark ignored {name}")
            denials[name] = count

        result = read()
        assert result["digest"] == pins["benchmark_run_digest"]
        assert result["metrics"] == pins["benchmark_metrics"]
        assert result["judgements_sha256"] == pins["benchmark_judgements_sha256"]
        assert result["review"]["action"] == "ACCEPT"
        assert result["review"]["reviewer"] == "publisher"
        assert result["promotion_performed"] is False and result["synthetic_only"] is True
        assert result["metrics"]["summary"]["baseline"]["recall_at_5"] == 0.5
        assert result["metrics"]["summary"]["candidate"]["recall_at_5"] == 1.0
        assert len(result["comparisons"]) == 3
        assert desk()["current"]["id"] == pins["benchmark_suite_id"]
        title = EvaluationRevision.objects.get(pk=pins["title_suite_id"])
        assert title.engine == "TITLE_WORDS" and title.number == 1
        assert workspace._digest(title.corpus) == pins["title_corpus_sha256"]
        assert review._data(title)["state"] == "PENDING"
        with override_settings(FATWA_CANONICAL_BENCHMARK_AUTHORITY=None):
            denied("missing_benchmark_authority")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            denied("missing_identity_provider")
        with override_settings(FATWA_CANONICAL_BENCHMARK_ENABLED=False):
            denied("disabled_feature")
        with override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=None):
            denied("missing_source_search_authority")
        authority.denied.add("READ")
        denied("revoked_read_action")
        authority.denied.clear()
        directory = base["provider"]
        original = directory.identities["editor"]
        directory.identities["editor"] = replace(original, active=False)
        try:
            denied("revoked_current_reader")
        finally:
            directory.identities["editor"] = original
        assert read()["digest"] == pins["benchmark_run_digest"]
        assert desk()["current"]["state"] == "APPROVE"
    assert _history(pins["case_id"]) == initial
    return {
        "denial_checks": denials,
        "denied_read_count": sum(denials.values()),
        "positive_reads_after_denial": True,
        "benchmark_history_unchanged": True,
        "actual_query_pairs": 3,
        "verified_engines": ["CANONICAL_FTS", "TITLE_WORDS"],
        "judgements_independently_reviewed": True,
        "run_independently_reviewed": True,
        "synthetic_only": True,
        "promotion_performed": False,
    }
