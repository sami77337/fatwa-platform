"""Synthetic Arabic content: exact round-trip and no silent mutation."""
from hashlib import sha256
import unittest

from apps.delivery_planner.planner import Capabilities, InvalidPlan
from apps.delivery_planner.segmentation import (
    SegmentationNeedsReview, parts_for_delivery, segment_text,
)


class SegmenterTests(unittest.TestCase):
    def test_short_answer_is_one_exact_part(self):
        source = "جوابٌ عربيّ، كما كُتب.\r\n"
        sections = segment_text(source, max_chars=280)
        self.assertEqual([s.exact_text for s in sections], [source])
        self.assertEqual(sections[0].sha256, sha256(source.encode()).hexdigest())

    def test_long_answer_requires_explicit_choice(self):
        source = ("هذا سؤالٌ طويل. " * 20).strip()
        with self.assertRaises(SegmentationNeedsReview):
            segment_text(source, max_chars=80)
        sections = segment_text(source, max_chars=80, explicit_human_choice=True)
        self.assertGreater(len(sections), 1)
        self.assertEqual("".join(section.exact_text for section in sections), source)
        self.assertTrue(all(len(section.exact_text) <= 80 for section in sections))
        self.assertEqual([s.ordinal for s in sections], list(range(1, len(sections) + 1)))

    def test_keep_diacritics_crlf_and_whitespace(self):
        source = "  اسمٌ  معَ تَشْكِيل\r\nفقرةٌ ثانية  \nونهاية"
        parts = segment_text(source, max_chars=22, explicit_human_choice=True)
        self.assertEqual("".join(p.exact_text for p in parts), source)
        self.assertFalse(any(p.exact_text.endswith("\r") for p in parts))

    def test_long_unbreakable_word_and_capacity_refuse_truncation(self):
        with self.assertRaises(SegmentationNeedsReview):
            segment_text("م" * 101, max_chars=20, explicit_human_choice=True)
        with self.assertRaises(SegmentationNeedsReview):
            segment_text("كلمة " * 80, max_chars=10, explicit_human_choice=True)
        with self.assertRaises(InvalidPlan):
            segment_text("أ", max_chars=True)

    def test_planner_parts_share_exact_hashes(self):
        cap = Capabilities("comment", "v2", frozenset({"text"}), 42, False)
        source = "كلمة وعنوان مكرر. " * 7
        parts, exact = parts_for_delivery(source, cap, explicit_human_choice=True)
        self.assertEqual("".join(x.exact_text for x in exact), source)
        self.assertEqual(tuple(p.sha256 for p in parts), tuple(x.sha256 for x in exact))
        self.assertTrue(all(p.media_type == "text" and p.length <= 42 for p in parts))
        with self.assertRaises(SegmentationNeedsReview):
            parts_for_delivery(source, Capabilities("comment", "v2", frozenset(), 42, False))


if __name__ == "__main__":
    unittest.main()
