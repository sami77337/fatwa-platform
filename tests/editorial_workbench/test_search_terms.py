"""Regression for Arabic phrase variants in the private training case queue."""
import unittest

from apps.editorial_workbench.search_terms import case_search_matches, normalize_case_search
from apps.reference.normalization import normalize_title


class CaseSearchTests(unittest.TestCase):
    def test_negative_preposition_variants(self):
        for query in ("بدون مقطع", "بلا مقطع", "دون مقطع"):
            for saved in ("بلا مقطع", "بدون مقطع", "دون مقطع"):
                with self.subTest(query=query, saved=saved):
                    self.assertTrue(case_search_matches(query, "ما الحكم في التسجيل " + saved + " للصوت؟"))

    def test_preserves_word_boundaries(self):
        self.assertFalse(case_search_matches("دون مقطع", "ملف تدوين مقطع"))
        self.assertFalse(case_search_matches("بدون مقطع", "الحكم بدون مقصد"))

    def test_unchanged_catalog_title_normalization(self):
        before = "السؤال بدون مقطع"
        self.assertEqual(normalize_title(before), "السؤال بدون مقطع")
        self.assertEqual(normalize_case_search(before), "السؤال بلا مقطع")

    def test_diacritics_and_misses(self):
        self.assertTrue(case_search_matches("إِجابةٌ بلا مقطع", "إجابة بدون مقطع"))
        self.assertFalse(case_search_matches("بلا مقطع", "بلا مسار"))
        self.assertFalse(case_search_matches("صلاة", "زكاة بلا مقطع"))


if __name__ == "__main__":
    unittest.main()
