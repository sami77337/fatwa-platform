from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_queue.services import build_queue_catalog
from tests.editorial_search import evaluate_relevance as evaluation


class RelevanceEvaluationTests(SimpleTestCase):
    def test_top_three_cutoff_denominators_and_position(self):
        a, b, c, d = ((key, None) for key in "abcd")
        result = evaluation.score((b, c, a, d), (a, d))
        self.assertEqual(result["returned_at_k"], (b, c, a))
        self.assertEqual(result["true_positives"], 1)
        self.assertAlmostEqual(result["precision_at_k"], 1 / 3)
        self.assertAlmostEqual(result["recall_at_k"], 1 / 2)
        self.assertAlmostEqual(result["reciprocal_rank_at_k"], 1 / 3)

    def test_short_lists_use_k_and_unanswerable_queries_score_separately(self):
        a = ("a", None)
        self.assertEqual(evaluation.score((a,), (a,))["precision_at_k"], 1 / 3)
        self.assertEqual(evaluation.score((), (a,))["recall_at_k"], 0)
        result = evaluation.score((a,), ())
        self.assertFalse(result["correct_empty"])
        self.assertIsNone(result["recall_at_k"])
        self.assertIsNone(result["reciprocal_rank_at_k"])

    def test_duplicate_retrieved_identity_cannot_inflate_precision(self):
        a = ("a", 4)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluation.score((a, a), (a,))

    def test_invalid_fixture_identity_cannot_masquerade_as_retrieval_failure(self):
        case = replace(evaluation.CASES[0], relevant=(("absent-case", None),))
        with patch.object(evaluation, "CASES", (case,)):
            with self.assertRaisesRegex(ValueError, "unknown judgment"):
                evaluation.evaluate(build_queue_catalog())

    def test_actual_synthetic_engine_report_and_controls(self):
        report = evaluation.evaluate(build_queue_catalog())
        rows = {r["id"]: r for r in report["queries"]}
        self.assertEqual(report["cutoff"], 3)
        self.assertEqual(rows["exact-question"]["returned_at_k"][0], ("intake-3", None))
        self.assertEqual(rows["marked-duplicates"]["recall_at_k"], 1)
        self.assertEqual(rows["cross-batch-copies"]["precision_at_k"], 1)
        self.assertEqual(
            rows["gapped-revisions"]["returned_at_k"],
            (("history", 2), ("history", 4), ("history", 7)),
        )
        self.assertEqual(rows["gapped-revisions"]["recall_at_k"], 3 / 5)
        self.assertTrue(rows["no-match-control"]["correct_empty"])
        positives = [r for r in rows.values() if r["relevant_ids"]]
        for field in ("precision_at_k", "recall_at_k", "reciprocal_rank_at_k"):
            self.assertAlmostEqual(
                report["macro"][field], sum(r[field] for r in positives) / len(positives)
            )
        self.assertEqual(
            report["query_coverage_at_k"],
            sum(r["true_positives"] > 0 for r in positives) / len(positives),
        )
        self.assertEqual(report["empty_controls"], {"correct": 1, "total": 1})
