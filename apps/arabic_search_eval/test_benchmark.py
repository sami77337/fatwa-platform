"""Real PostgreSQL retrieval, independent judgments and current-source invalidation."""

import uuid
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

from django.db import DatabaseError, IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from apps.canonical_search import governance
from apps.canonical_search import services as search
from apps.canonical_search.governance_test_support import TERM
from apps.canonical_search.models import SearchDocument, ShadowComparison
from apps.casework import services as cases
from apps.casework.models import CaseEvent, CaseSource
from apps.mufti_review.identity import IdentityUnavailable
from apps.research_workspace import services as workspace
from apps.research_workspace.tests import SyntheticRights

from . import benchmark, review
from .benchmark_test_support import FEATURES, BenchmarkFixture
from .models import (
    CanonicalBenchmarkDecision,
    CanonicalBenchmarkRun,
    EvaluationDecision,
    EvaluationRevision,
)
from .views import proposed_bundle


@override_settings(**FEATURES)
class CanonicalBenchmarkTests(BenchmarkFixture, TransactionTestCase):
    def test_actual_retrieval_nontrivial_precision_recall_rank_coverage_and_independent_accept(
        self,
    ):
        suite, dictionary = self.ready()
        events = CaseEvent.objects.count()
        source = CaseSource.objects.get(case_id=self.common["case_id"]).original_question
        result = self.execute(suite, dictionary)
        self.assertEqual(result["regression_status"], "CLEAR")
        self.assertEqual(
            result["metrics"]["counts"],
            {"queries": 3, "positive": 2, "negative": 1, "candidate_errors": 0},
        )
        alias, partial, negative = result["metrics"]["queries"]
        self.assertEqual(alias["baseline"], [])
        self.assertEqual(alias["candidate"], [self.documents["QUESTION"], self.documents["ANSWER"]])
        self.assertEqual(
            alias["candidate_score"],
            {
                "precision_at_5": 0.5,
                "recall_at_5": 1.0,
                "reciprocal_rank": 1.0,
                "exact_order": False,
            },
        )
        self.assertEqual(partial["baseline_score"]["recall_at_5"], 0.5)
        self.assertEqual(partial["candidate_score"]["recall_at_5"], 0.5)
        self.assertEqual(negative["candidate"], [])
        before, after = [result["metrics"]["summary"][name] for name in ("baseline", "candidate")]
        self.assertEqual((before["precision_at_5"], after["precision_at_5"]), (0.5, 0.75))
        self.assertEqual((before["recall_at_5"], after["recall_at_5"]), (0.25, 0.75))
        self.assertEqual((before["reciprocal_rank"], after["reciprocal_rank"]), (0.5, 1.0))
        self.assertEqual(
            (before["judged_query_hit_coverage_at_5"], after["judged_query_hit_coverage_at_5"]),
            (0.5, 1.0),
        )
        self.assertGreater(result["workload"]["sql_selects"], 0)
        self.assertGreaterEqual(
            result["workload"]["sql_statements"], result["workload"]["sql_selects"]
        )
        self.assertIsNone(result["workload"]["monetary_cost"])
        self.assertEqual(result["workload"]["external_ai_calls"], 0)
        self.assertFalse(result["promotion_performed"])
        self.assertEqual(ShadowComparison.objects.count(), 3)
        self.assertEqual(search.search(**self.common, value=TERM, mode="FTS")["total"], 0)
        self.assertEqual(search.search(**self.common, value=TERM, mode="LITERAL")["total"], 0)
        with self.assertRaisesMessage(cases.CaseConflict, "independent_reviewer"):
            self.run_decision(result, subject_id="editor")
        approved = self.run_decision(result)
        self.assertEqual(approved["review"]["action"], "ACCEPT")
        self.assertEqual(approved["review"]["reviewer"], "other")
        reread = benchmark.read(**self.common, run_id=result["id"])
        self.assertEqual(reread["metrics"], result["metrics"])
        self.assertEqual(CaseEvent.objects.count(), events)
        self.assertEqual(
            CaseSource.objects.get(case_id=self.common["case_id"]).original_question, source
        )

    def test_authored_judgments_need_current_independent_review_and_do_not_inherit_approval(self):
        dictionary, _ = self.approved()
        suite = self.suite()
        with self.assertRaisesMessage(cases.CaseConflict, "unapproved"):
            self.execute(suite, dictionary)
        for changes in (
            {"subject_id": "editor"},
            {"confirmed": False},
            {"reviews": []},
            {"judgements_sha256": "0" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.judge(suite, **changes)
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        self.judge(suite)
        result = self.execute(suite, dictionary)
        changed = deepcopy(self.judgements)
        changed[0]["expected"].append(self.documents["ANSWER"])
        newer = self.suite(judgements=changed)
        self.assertEqual(newer["state"], "PENDING")
        self.assertNotEqual(newer["judgements_sha256"], suite["judgements_sha256"])
        with self.assertRaisesMessage(cases.CaseConflict, "suite_stale"):
            benchmark.read(**self.common, run_id=result["id"])
        self.judge(newer, action="REJECT")
        with self.assertRaisesMessage(cases.CaseConflict, "unapproved"):
            self.execute(newer, dictionary)

    def test_per_query_regression_cannot_be_accepted_even_when_other_query_improves(self):
        dictionary = self.revision(
            entries=[
                {"key": "alias", "term": TERM, "alternatives": ["المعاملات"]},
                {"key": "distractor", "term": "الزكاة", "alternatives": ["المعاملات"]},
            ]
        )
        preview = self.preview(dictionary)
        self.decide(dictionary, preview)
        judgments = deepcopy(self.judgements)
        judgments[1]["expected"] = [self.documents["QUESTION"]]
        suite = self.suite(judgements=judgments)
        self.judge(suite)
        result = self.execute(suite, dictionary)
        self.assertEqual(result["regression_status"], "HOLD")
        self.assertIn(
            {"id": "partial", "reason": "precision_at_5", "baseline": 1.0, "candidate": 0.5},
            result["regressions"],
        )
        with self.assertRaisesMessage(cases.CaseConflict, "regressions_require_hold"):
            self.run_decision(result)
        held = self.run_decision(result, action="HOLD")
        self.assertEqual(held["review"]["action"], "HOLD")
        self.assertFalse(held["promotion_performed"])

    def test_candidate_database_failure_records_error_and_retains_real_baseline(self):
        suite, dictionary = self.ready()
        with patch.object(
            governance, "_candidate", side_effect=DatabaseError("synthetic candidate failure")
        ):
            result = self.execute(suite, dictionary)
        self.assertEqual(result["metrics"]["counts"]["candidate_errors"], 3)
        self.assertEqual(result["regression_status"], "HOLD")
        self.assertEqual(result["metrics"]["queries"][1]["baseline"], [self.documents["QUESTION"]])
        self.assertEqual(search.search(**self.common, value="الزكاة")["total"], 1)
        with self.assertRaises(cases.CaseConflict):
            self.run_decision(result)
        self.assertEqual(
            benchmark.read(**self.common, run_id=result["id"])["metrics"], result["metrics"]
        )

    def test_current_source_generation_rights_and_dictionary_retirement_invalidate_reads(self):
        suite, dictionary = self.ready()
        result = self.execute(suite, dictionary)
        self.decide(dictionary, action="RETIRE", ttl_minutes=0, preview=None)
        with self.assertRaisesMessage(cases.CaseConflict, "not_currently_approved"):
            benchmark.read(**self.common, run_id=result["id"])
        self.answer("A later canonical answer version changes the corpus.")
        with self.assertRaises(cases.CaseConflict):
            benchmark.read(**self.common, run_id=result["id"])
        self.build()
        desk = benchmark.desk(**self.common)
        self.assertFalse(desk["current"]["current"])
        self.assertNotIn("judgements", desk["current"])
        self.assertNotIn("corpus", desk["current"])
        with self.assertRaisesMessage(cases.CaseConflict, "corpus_stale"):
            benchmark.read(**self.common, run_id=result["id"])

    def test_current_optional_source_revocation_denies_old_corpus_without_returning_private_copy(
        self,
    ):
        dictionary, _ = self.approved()
        self.transcript()
        self.build()
        self.judgements = [
            {
                "id": "one",
                "query": TERM,
                "expected": [
                    str(row.pk)
                    for row in SearchDocument.objects.filter(
                        generation__case_id=self.common["case_id"],
                        generation__number=2,
                        kind="QUESTION",
                    )
                ],
                "rationale": "Synthetic current question.",
            }
        ]
        suite = self.suite()
        # This fixture's other reviewer cannot read the editor-owned transcript;
        # judgment approval itself must fail closed on the corpus mismatch.
        with self.assertRaisesMessage(cases.CaseConflict, "corpus_stale"):
            self.judge(suite)

        class SharedFixtureRights(SyntheticRights):
            def permits(self, **values):
                return (
                    values["provider_id"] == "synthetic-publication-directory"
                    and values["subject_id"] in {"editor", "other"}
                    and values["auth_epoch"] == "epoch-1"
                    and values["case_ref"] == self.ref
                    and (values["resource"].kind, values["action"]) not in self.denied
                )

        with override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SharedFixtureRights(self.receipt["public_ref"])
        ):
            self.judge(suite)
            result = self.execute(suite, dictionary)
            self.knowledge.allow_open = False
            with self.assertRaisesMessage(cases.CaseConflict, "corpus_stale"):
                benchmark.read(**self.common, run_id=result["id"])
            self.assertFalse(benchmark.desk(**self.common)["current"]["current"])
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 1)

    def test_code_dictionary_hash_expiry_and_cross_case_inputs_are_rejected(self):
        suite, dictionary = self.ready()
        result = self.execute(suite, dictionary)
        for changes in (
            {"expected_corpus_sha256": "0" * 64},
            {"expected_judgements_sha256": "0" * 64},
            {"expected_dictionary_digest": "0" * 64},
            {"revision_id": uuid.uuid4()},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.execute(suite, dictionary, **changes)
        changed_code = {**benchmark.code_pin(), "version": "changed"}
        with patch.object(benchmark, "code_pin", return_value=changed_code):
            with self.assertRaisesMessage(cases.CaseConflict, "suite_stale"):
                benchmark.read(**self.common, run_id=result["id"])
        from datetime import timedelta

        from django.utils import timezone

        future = timezone.now() + timedelta(minutes=61)
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, valid_until=future + timedelta(hours=1)
            )
        with patch("apps.canonical_search.governance.timezone.now", return_value=future):
            with self.assertRaisesMessage(cases.CaseConflict, "not_currently_approved"):
                benchmark.read(**self.common, run_id=result["id"])

    def test_defaults_explicit_actions_identity_replacement_and_final_callback_revocation(self):
        suite, dictionary = self.ready()
        for name, value in (
            ("FATWA_CANONICAL_BENCHMARK_ENABLED", False),
            ("FATWA_CANONICAL_BENCHMARK_ENABLED", 1),
            ("FATWA_CANONICAL_BENCHMARK_AUTHORITY", None),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with (
                self.subTest(name=name, value=value),
                override_settings(**{name: value}),
                self.assertRaises(cases.CaseConflict),
            ):
                self.execute(suite, dictionary)
        for action in ("RUN", "READ"):
            self.benchmark_authority.denied.add(action)
            with self.assertRaises(cases.CaseConflict):
                self.execute(suite, dictionary)
            self.benchmark_authority.denied.clear()
        from apps.canonical_search import services

        seal = services._seal

        def revoke(row):
            created = seal(row)
            if isinstance(row, CanonicalBenchmarkRun):
                self.benchmark_authority.denied.add("RUN")
            return created

        with (
            patch.object(services, "_seal", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.execute(suite, dictionary)
        self.benchmark_authority.denied.clear()
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 0)
        self.assertEqual(ShadowComparison.objects.count(), 0)
        actor = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(actor, active=False)
        with self.assertRaises(IdentityUnavailable):
            benchmark.desk(**self.common)

    def test_final_search_permission_callback_cannot_change_benchmark_authority_after_its_callback(
        self,
    ):
        suite, dictionary = self.ready()

        def revoke(values):
            if values["action"] == "SEARCH" and CanonicalBenchmarkRun.objects.exists():
                self.benchmark_authority.denied.add("RUN")

        self.authority.hook = revoke
        with self.assertRaisesMessage(cases.CaseConflict, "authority_changed"):
            self.execute(suite, dictionary)
        self.authority.hook = None
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 0)
        self.assertEqual(ShadowComparison.objects.count(), 0)

    def test_corpus_scope_bounds_bad_expectations_and_sql_immutability(self):
        for change in (
            [{**self.judgements[0], "expected": [str(uuid.uuid4())]}],
            [{**self.judgements[0], "expected": [self.documents["QUESTION"]] * 2}],
            self.judgements * 3,
            [self.judgements[0], self.judgements[0]],
        ):
            with self.subTest(change=change), self.assertRaises(cases.CaseConflict):
                self.suite(judgements=change)
        suite, dictionary = self.ready()
        result = self.execute(suite, dictionary)
        self.run_decision(result)
        operations = (
            lambda: EvaluationRevision.objects.filter(pk=suite["id"]).update(note="changed"),
            lambda: EvaluationDecision.objects.filter(revision_id=suite["id"]).update(
                note="changed"
            ),
            lambda: CanonicalBenchmarkRun.objects.filter(pk=result["id"]).update(note="changed"),
            lambda: CanonicalBenchmarkDecision.objects.filter(run_id=result["id"]).delete(),
        )
        for operation in operations:
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_title_word_corpus_review_and_sequence_remain_independent(self):
        from .test_review import Authority

        self.suite()
        bundle = proposed_bundle()
        bundle["queries"] = bundle["queries"][:2]
        with override_settings(
            FATWA_ARABIC_SEARCH_REVIEW_ENABLED=True,
            FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY=Authority(self.receipt["public_ref"]),
        ):
            original = review.propose(
                **self.common,
                expected_number=0,
                bundle=bundle,
                note="Unchanged title fixture workflow.",
            )
            self.assertEqual(original["number"], 1)
            self.assertEqual(
                original["corpus"],
                {key: bundle[key] for key in ("synthetic_only", "clock", "records")},
            )
            self.assertEqual(original["judgements_sha256"], workspace._digest(bundle["queries"]))
            reviewed = review.decide(
                **{**self.common, "subject_id": "publisher"},
                revision_id=original["id"],
                corpus_sha256=original["corpus_sha256"],
                judgements_sha256=original["judgements_sha256"],
                action="APPROVE",
                confirmed=True,
                reviews=[
                    {
                        "id": q["id"],
                        "verdict": "AGREE",
                        "note": "Old independent title-word fixture review.",
                    }
                    for q in bundle["queries"]
                ],
                note="Preserved old semantics.",
            )
            self.assertEqual(reviewed["state"], "APPROVE")
            self.assertEqual(len(review.history(**self.common)["versions"]), 1)
            self.assertEqual(benchmark.desk(**self.common)["current"]["number"], 1)

    def test_identical_request_replays_without_new_run_shadow_or_implicit_search_activation(self):
        suite, dictionary = self.ready()
        key = uuid.uuid4()
        result = self.execute(suite, dictionary, request_key=key)
        replay = self.execute(suite, dictionary, request_key=key)
        self.assertEqual(replay["id"], result["id"])
        self.assertEqual(replay["digest"], result["digest"])
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 1)
        self.assertEqual(ShadowComparison.objects.count(), 3)
        with self.assertRaisesMessage(cases.CaseConflict, "request_conflict"):
            self.execute(suite, dictionary, request_key=key, note="Changed request.")

    def test_negative_query_false_positives_are_reported_separately_and_force_hold(self):
        dictionary, _ = self.approved()
        judgements = deepcopy(self.judgements)
        judgements[0]["expected"] = []
        suite = self.suite(judgements=judgements)
        self.judge(suite)
        result = self.execute(suite, dictionary)
        self.assertEqual(result["regression_status"], "HOLD")
        self.assertEqual(result["metrics"]["counts"]["negative"], 2)
        self.assertEqual(
            result["metrics"]["summary"]["baseline"]["negative_false_positive_queries"], 0
        )
        self.assertEqual(
            result["metrics"]["summary"]["candidate"]["negative_false_positive_queries"], 1
        )
        self.assertEqual(
            result["metrics"]["summary"]["candidate"]["negative_returned_documents"], 2
        )
        self.assertIn(
            {"id": "alias", "reason": "negative_false_positives", "baseline": 0, "candidate": 2},
            result["regressions"],
        )
        with self.assertRaisesMessage(cases.CaseConflict, "regressions_require_hold"):
            self.run_decision(result)

    def test_database_rejects_forged_source_judgment_comparison_and_self_run_review(self):
        suite, dictionary = self.ready()
        result = self.execute(suite, dictionary)
        forged_suite = deepcopy(EvaluationRevision.objects.get(pk=suite["id"]))
        forged_suite.pk, forged_suite.number = uuid.uuid4(), 2
        forged_suite.judgements[0]["expected"] = [str(uuid.uuid4())]
        forged_suite.judgements_sha256 = workspace._digest(forged_suite.judgements)
        with self.assertRaisesMessage(IntegrityError, "outside corpus"), transaction.atomic():
            forged_suite.save(force_insert=True)
        row = CanonicalBenchmarkRun.objects.get(pk=result["id"])
        forged_run = deepcopy(row)
        forged_run.pk, forged_run.request_key = uuid.uuid4(), uuid.uuid4()
        forged_run.comparisons[0]["digest"] = "0" * 64
        with (
            self.assertRaisesMessage(IntegrityError, "exact actual comparison"),
            transaction.atomic(),
        ):
            search._seal(forged_run)
        self_review = CanonicalBenchmarkDecision(
            case_id=row.case_id,
            case_revision=row.case_revision,
            evidence_version=row.evidence_version,
            provider_id=row.provider_id,
            subject_id=row.subject_id,
            auth_epoch=row.auth_epoch,
            request_key=uuid.uuid4(),
            run=row,
            action="ACCEPT",
            note="Forbidden self-review from a raw write.",
        )
        with (
            self.assertRaisesMessage(IntegrityError, "independent current run review"),
            transaction.atomic(),
        ):
            search._seal(self_review)
        self.assertEqual(CanonicalBenchmarkDecision.objects.count(), 0)
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 1)
