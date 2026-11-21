"""Authored synthetic relevance expectations; never a specialist gold benchmark."""

import uuid
from copy import deepcopy

from django.test import override_settings

from apps.canonical_search.governance_test_support import FEATURES as GOVERNANCE_FEATURES
from apps.canonical_search.governance_test_support import TERM, GovernanceFixture
from apps.canonical_search.models import SearchDocument

from . import benchmark
from .benchmark_policy import ACTIONS, CanonicalBenchmarkAuthority

FEATURES = {**GOVERNANCE_FEATURES, "FATWA_CANONICAL_BENCHMARK_ENABLED": True}


class BenchmarkAuthority(CanonicalBenchmarkAuthority):
    def __init__(self, ref):
        self.ref, self.denied, self.hook, self.calls = ref, set(), None, []

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied)))

    def permits(self, **values):
        self.calls.append(values)
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["auth_epoch"] == "epoch-1"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["case_ref"] == self.ref
            and values["action"] in ACTIONS
            and values["action"] not in self.denied
        )


class BenchmarkFixture(GovernanceFixture):
    def setUp(self):
        super().setUp()
        self.benchmark_authority = BenchmarkAuthority(self.receipt["public_ref"])
        configured = override_settings(FATWA_CANONICAL_BENCHMARK_AUTHORITY=self.benchmark_authority)
        configured.enable()
        self.addCleanup(configured.disable)
        self.documents = {
            row.kind: str(row.pk)
            for row in SearchDocument.objects.filter(generation__case_id=self.common["case_id"])
        }
        self.judgements = [
            {
                "id": "alias",
                "query": TERM,
                "expected": [self.documents["QUESTION"]],
                "rationale": "Authored synthetic judgment: the question is relevant; the answer is a distractor for this query.",
            },
            {
                "id": "partial",
                "query": "الزكاة",
                "expected": [self.documents["QUESTION"], self.documents["ANSWER"]],
                "rationale": "Authored synthetic judgment expects both case texts; lexical retrieval omits the answer.",
            },
            {
                "id": "negative",
                "query": "غيرموجوداصطناعيا",
                "expected": [],
                "rationale": "This made-up token has no relevant source in the synthetic corpus.",
            },
        ]

    def suite(self, **changes):
        desk = benchmark.desk(**self.common)
        return benchmark.propose(
            **{
                **self.common,
                "expected_number": desk["current_number"],
                "expected_corpus_sha256": desk["corpus_sha256"],
                "judgements": deepcopy(self.judgements),
                "note": "Synthetic authored expectations, not real gold review.",
                **changes,
            }
        )

    def judge(self, row, **changes):
        return benchmark.judge(
            **{
                **self.common,
                "subject_id": "other",
                "revision_id": row["id"],
                "corpus_sha256": row["corpus_sha256"],
                "judgements_sha256": row["judgements_sha256"],
                "action": "APPROVE",
                "confirmed": True,
                "reviews": [
                    {
                        "id": item["id"],
                        "verdict": "AGREE",
                        "note": "Explicit independent synthetic reviewer fixture.",
                    }
                    for item in row["judgements"]
                ],
                "note": "Synthetic independent judgment decision.",
                **changes,
            }
        )

    def execute(self, suite, dictionary, **changes):
        return benchmark.run(
            **{
                **self.common,
                "revision_id": suite["id"],
                "dictionary_id": dictionary["id"],
                "expected_corpus_sha256": suite["corpus_sha256"],
                "expected_judgements_sha256": suite["judgements_sha256"],
                "expected_dictionary_digest": dictionary["digest"],
                "request_key": uuid.uuid4(),
                "note": "Measure actual PostgreSQL baseline and explicit candidate.",
                **changes,
            }
        )

    def ready(self):
        dictionary, _ = self.approved()
        suite = self.suite()
        self.judge(suite)
        return suite, dictionary

    def run_decision(self, row, **changes):
        return benchmark.decide(
            **{
                **self.common,
                "subject_id": "other",
                "run_id": row["id"],
                "expected_digest": row["digest"],
                "action": "ACCEPT",
                "confirmed": True,
                "note": "Independent decision for the exact synthetic run only.",
                "request_key": uuid.uuid4(),
                **changes,
            }
        )
