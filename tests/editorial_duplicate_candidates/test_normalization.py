"""Conservative Unicode equivalence, preserving potentially meaningful differences."""

import unittest

from apps.editorial_duplicate_candidates.services import DuplicateCandidateError, normalize_text


class NormalizationTests(unittest.TestCase):
    def test_arabic_vowels_crlf_spaces_and_canonical_unicode(self):
        original = "  سُؤَالٌ اصطناعي\r\nبِسطرٍ e\u0301\t "
        self.assertEqual(normalize_text(original), "سؤال اصطناعي بسطر é")
        self.assertEqual(normalize_text("ا\u0654مر"), normalize_text("أمر"))
        self.assertEqual(normalize_text("ا\u0653ن"), normalize_text("آن"))
        self.assertEqual(normalize_text("سؤال\u00a0اصطناعي"), "سؤال اصطناعي")

    def test_does_not_fold_meaningful_letters_punctuation_case_or_compatibility(self):
        for left, right in (
            ("أمر", "امر"),
            ("إمر", "امر"),
            ("آن", "ان"),
            ("على", "علي"),
            ("رحمة", "رحمه"),
            ("سؤال؟", "سؤال"),
            ("Case", "case"),
            ("é", "e"),
            ("ﻻ", "لا"),
            ("عـلم", "علم"),
            ("هٰذا", "هذا"),
            ("س\u200dؤال", "سؤال"),
        ):
            with self.subTest(left=left, right=right):
                self.assertNotEqual(normalize_text(left), normalize_text(right))

    def test_normalization_is_idempotent_and_blank_stays_blank(self):
        for value in ("", " \r\n\t", "\u064b\u0652", "سُؤَالٌ\r\n e\u0301", "ا\u0654"):
            with self.subTest(value=value):
                normalized = normalize_text(value)
                self.assertEqual(normalize_text(normalized), normalized)
        self.assertEqual(normalize_text(" \u064b\t\u0652"), "")

    def test_rejects_non_text_surrogates_and_oversized_text(self):
        for value in (None, 123, b"bytes", "\ud800", "x" * 65537):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(DuplicateCandidateError):
                    normalize_text(value)
