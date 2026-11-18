"""Focused pure normalization, ranking, metrics, and review-binding checks."""

import copy
import unittest

from .evaluation import evaluate, review_template, score, validate_review
from .ranking import Candidate, query_tokens, rank_titles, tokens


class RankingTests(unittest.TestCase):
    def test_explicit_fixture_expectations_and_negative_queries(self):
        report = evaluate()
        self.assertEqual(report["counts"]["queries"], 42)
        self.assertEqual(report["human_review"], "PENDING")
        for row in report["queries"]:
            with self.subTest(query=row["id"]):
                self.assertTrue(row["improved_score"]["exact_order"])
                self.assertTrue(row["error_matches"])
                self.assertEqual(row["forbidden_hits"], 0)
        self.assertGreater(
            report["summary"]["improved"]["recall_at_5"],
            report["summary"]["baseline"]["recall_at_5"],
        )

    def test_shared_normalization_is_idempotent_and_does_not_destroy_distinctions(self):
        text = "أَبْوَاب ۱۲ كـتاب دراسة بيئة مسؤول"
        result = tokens(text)
        self.assertEqual(tokens(" ".join(result)), result)
        self.assertEqual(result, ("ابواب", "12", "كتاب", "دراسة", "بيئة", "مسؤول"))
        self.assertNotEqual(tokens("دراسة"), tokens("دراسه"))
        self.assertNotEqual(tokens("بيئة"), tokens("بيية"))
        self.assertNotEqual(tokens("مسؤول"), tokens("مسوول"))

    def test_whole_numbers_decimal_and_word_multiplicity(self):
        rows = [Candidate(str(i), t) for i, t in enumerate(["112", "12.5", "12", "012", "١٢"])]
        original = copy.deepcopy(rows)
        self.assertEqual([r.identifier for r in rank_titles("12", rows)], ["2", "4"])
        self.assertEqual(rows, original)
        self.assertEqual(rank_titles("باب باب", [Candidate("x", "باب")]), [])

    def test_stable_ties_and_explicit_rank_reasons(self):
        rows = [
            Candidate("a", "مدخل أبواب البحث"),
            Candidate("b", "ابواب البحث"),
            Candidate("c", "أبواب البحث"),
            Candidate("d", "البحث في أبواب"),
        ]
        hits = rank_titles("أبواب البحث", rows)
        self.assertEqual([h.identifier for h in hits], ["c", "b", "a", "d"])
        self.assertEqual([h.tier for h in hits], [0, 1, 2, 3])

    def test_rejects_duplicate_ids_large_windows_and_invalid_queries(self):
        for rows in ([Candidate("a", "باب")] * 2, [Candidate(str(i), "باب") for i in range(65)]):
            with self.assertRaises(ValueError):
                rank_titles("باب", rows)
        for query in (None, "", "َُ", "?!", "a" * 81, "a " * 11, "a\nb", "باب\ud800"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                query_tokens(query)

    def test_metrics_do_not_count_duplicates_and_define_empty_denominators(self):
        with self.assertRaises(ValueError):
            score(["a"], ["a", "a"])
        self.assertEqual(score(["a", "b"], ["x", "a"])["precision_at_5"], 0.5)
        self.assertEqual(score(["a", "b"], ["x", "a"])["recall_at_5"], 0.5)
        self.assertIsNone(score([], [])["recall_at_5"])
        self.assertEqual(score(["a"], [])["precision_at_5"], 0)

    def test_pending_stale_incomplete_and_altered_review_are_not_approval(self):
        review = review_template()
        with self.assertRaises(ValueError):
            validate_review(review)
        # Synthetic validator input only: not a real reviewer or reviewed dataset.
        review.update(reviewer="validator-fixture", evidence_reference="synthetic://test-only")
        for row in review["queries"]:
            row.update(verdict="AGREE", note="validator fixture only")
        self.assertIn("REQUIRES_INDEPENDENT", validate_review(review))
        for mutation in (
            lambda r: r.update(fixture_sha256="stale"),
            lambda r: r["queries"].pop(),
            lambda r: r["queries"][0].update(expected=[]),
            lambda r: r["queries"][0].update(verdict="PENDING"),
        ):
            invalid = copy.deepcopy(review)
            mutation(invalid)
            with self.assertRaises(ValueError):
                validate_review(invalid)
