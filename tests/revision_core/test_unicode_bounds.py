"""Synthetic Unicode and work-bound regressions; no fixtures, database, or timing gates."""

import unicodedata
import unittest
from dataclasses import replace
from unittest.mock import call, patch

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem
from apps.revision_core import revision_comparison as comparison
from apps.revision_core import revision_history as history

TEXT_FIELDS = ("title", "answer", "reviewer_notes")


def synthetic_revision(**changes):
    return replace(
        Revision(
            number=1,
            action="synthetic_snapshot",
            human_editor="synthetic editor",
            editorial_note="synthetic Unicode regression",
            state=State.RECEIVED,
            title="",
            answer="",
            reference_links=(),
            reviewer_notes="",
        ),
        **changes,
    )


def synthetic_record(*revisions):
    return DraftRecord(
        IntakeItem("synthetic-unicode", "Synthetic question", "https://example.invalid/clip"),
        revisions,
    )


class UnicodeComparisonTests(unittest.TestCase):
    def assert_reconstruction(self, result, before, after):
        self.assertEqual(tuple(field.key for field in result.fields), TEXT_FIELDS)
        for field in result.fields:
            self.assertEqual("".join(part.text for part in field.before), getattr(before, field.key))
            self.assertEqual("".join(part.text for part in field.after), getattr(after, field.key))
            self.assertTrue(all(part.kind in {"unchanged", "removed"} for part in field.before))
            self.assertTrue(all(part.kind in {"unchanged", "added"} for part in field.after))

    def test_combining_zwj_bidi_and_crlf_edits_preserve_exact_codepoints(self):
        # Dropping format characters or diffing graphemes would lose these edits.
        cases = (
            ("combining", "x\u0628\u064ey", "x\u0628\u064fy", "\u064e", "\u064f"),
            ("zwj", "\U0001f469\U0001f4bb", "\U0001f469\u200d\U0001f4bb", "", "\u200d"),
            ("variation", "x\u2764y", "x\u2764\ufe0fy", "", "\ufe0f"),
            ("bidi", "a\u2067b\u2069c", "a\u202eb\u202cc", "\u2067\u2069", "\u202e\u202c"),
            ("crlf", "a\r\nb\t c", "a\nb\t  c", "\r", " "),
        )
        for name, old, new, removed, added in cases:
            for key in TEXT_FIELDS:
                with self.subTest(case=name, field=key):
                    before = synthetic_revision(**{key: old})
                    after = replace(before, **{key: new})
                    result = comparison.compare_revisions(before, after)
                    self.assert_reconstruction(result, before, after)
                    field = next(field for field in result.fields if field.key == key)
                    self.assertTrue(field.changed)
                    self.assertEqual("".join(p.text for p in field.before if p.kind == "removed"),
                                     removed)
                    self.assertEqual("".join(p.text for p in field.after if p.kind == "added"),
                                     added)
                    self.assertEqual(tuple(target.anchor for target in result.targets),
                                     ("change-" + key,))

    def test_canonically_equivalent_combining_order_is_still_a_change(self):
        old, new = "q\u0323\u0307z", "q\u0307\u0323z"
        self.assertEqual(unicodedata.normalize("NFC", old), unicodedata.normalize("NFC", new))
        before = synthetic_revision(**dict.fromkeys(TEXT_FIELDS, old))
        after = replace(before, **dict.fromkeys(TEXT_FIELDS, new))
        result = comparison.compare_revisions(before, after)
        self.assert_reconstruction(result, before, after)
        self.assertTrue(all(field.changed for field in result.fields))
        self.assertEqual(len(result.targets), 3)

    def test_unchanged_complex_text_and_empty_fields_have_no_changes(self):
        for value in ("", "\u0628\u064e\u200d\U0001f4bb\u2067x\u2069\r\n\t "):
            with self.subTest(value=value):
                revision = synthetic_revision(**dict.fromkeys(TEXT_FIELDS, value))
                result = comparison.compare_revisions(revision, revision)
                self.assert_reconstruction(result, revision, revision)
                self.assertFalse(result.changed)
                self.assertEqual(result.targets, ())
                for field in result.fields:
                    expected = (("unchanged", value),) if value else ()
                    self.assertEqual(tuple((part.kind, part.text) for part in field.before), expected)
                    self.assertEqual(field.before, field.after)

    def test_ambiguous_short_repetition_is_deterministic_in_each_direction(self):
        old = "ab" * 24 + "\u0628\u064e\u200d\r\n" + "ab" * 12
        new = "ba" * 24 + "\u0628\u064f\r\n" + "ab" * 12
        before = synthetic_revision(**dict.fromkeys(TEXT_FIELDS, old))
        after = replace(before, number=2, **dict.fromkeys(TEXT_FIELDS, new))
        for left, right in ((before, after), (after, before)):
            expected = comparison.compare_revisions(left, right)
            self.assert_reconstruction(expected, left, right)
            self.assertTrue(all(field.changed for field in expected.fields))
            for _ in range(3):
                self.assertEqual(comparison.compare_revisions(left, right), expected)

    def test_invalid_unicode_in_either_revision_is_rejected_before_any_diff(self):
        valid = synthetic_revision(title="valid")
        for invalid in ("\ud800", "\udfff", "\ud83d\udcbb"):
            for key in TEXT_FIELDS:
                for side in ("before", "after"):
                    with self.subTest(value=ascii(invalid), field=key, side=side):
                        bad = replace(valid, **{key: "prefix" + invalid + "suffix"})
                        before, after = (bad, valid) if side == "before" else (valid, bad)
                        with patch.object(comparison, "SequenceMatcher") as matcher:
                            with self.assertRaises(ValueError) as raised:
                                comparison.compare_revisions(before, after)
                            matcher.assert_not_called()
                        self.assertEqual(str(raised.exception), "comparison_text_invalid_unicode")
                        self.assertIsInstance(raised.exception.__cause__, UnicodeEncodeError)

    def test_non_text_fields_in_either_revision_are_rejected_before_any_diff(self):
        valid = synthetic_revision(title="valid")
        for invalid in (None, b"text", 1):
            for key in TEXT_FIELDS:
                for side in ("before", "after"):
                    with self.subTest(value=invalid, field=key, side=side):
                        bad = replace(valid, **{key: invalid})
                        before, after = (bad, valid) if side == "before" else (valid, bad)
                        with patch.object(comparison, "SequenceMatcher") as matcher:
                            with self.assertRaises(ValueError) as raised:
                                comparison.compare_revisions(before, after)
                            matcher.assert_not_called()
                        self.assertEqual(str(raised.exception), "comparison_text_invalid_or_too_long")

    def test_10001_codepoints_in_either_revision_are_rejected_before_any_diff(self):
        valid = synthetic_revision(title="valid")
        for key in TEXT_FIELDS:
            for side in ("before", "after"):
                with self.subTest(field=key, side=side):
                    bad = replace(valid, **{key: "\U0001f4bb" * 10001})
                    before, after = (bad, valid) if side == "before" else (valid, bad)
                    with patch.object(comparison, "SequenceMatcher") as matcher:
                        with self.assertRaises(ValueError) as raised:
                            comparison.compare_revisions(before, after)
                        matcher.assert_not_called()
                    self.assertEqual(str(raised.exception), "comparison_text_invalid_or_too_long")

    def test_10000_astral_codepoints_are_accepted_without_a_byte_length_limit(self):
        # Unique scalars avoid a quadratic repeated-character workload at the bound.
        value = "".join(chr(0x10000 + index) for index in range(10000))
        self.assertEqual(len(value), 10000)
        self.assertEqual(len(value.encode("utf-8")), 40000)
        revision = synthetic_revision(**dict.fromkeys(TEXT_FIELDS, value))
        with patch.object(comparison, "SequenceMatcher", wraps=comparison.SequenceMatcher) as matcher:
            result = comparison.compare_revisions(revision, revision)
        self.assert_reconstruction(result, revision, revision)
        self.assertFalse(result.changed)
        self.assertEqual(matcher.call_args_list,
                         [call(None, value, value, autojunk=False)] * 3)

    def test_history_wraps_invalid_unicode_and_length_before_diffing_first_snapshot(self):
        for key in TEXT_FIELDS:
            for value, message in (("\udfff", "comparison_text_invalid_unicode"),
                                   ("x" * 10001, "comparison_text_invalid_or_too_long")):
                with self.subTest(field=key, error=message):
                    record = synthetic_record(synthetic_revision(**{key: value}))
                    with patch.object(comparison, "SequenceMatcher") as matcher:
                        with self.assertRaises(history.HistoryDataError) as raised:
                            history.build_history(record)
                        matcher.assert_not_called()
                    self.assertEqual(str(raised.exception), "invalid_history_content")
                    self.assertIsInstance(raised.exception.__cause__, ValueError)
                    self.assertEqual(str(raised.exception.__cause__), message)

    def test_maximum_history_uses_one_comparison_and_three_matchers_per_snapshot(self):
        revisions = tuple(synthetic_revision(number=index, title=str(index))
                          for index in range(1, 101))
        record = synthetic_record(*reversed(revisions))
        with (
            patch.object(history, "compare_revisions", wraps=history.compare_revisions) as compare,
            patch.object(comparison, "SequenceMatcher", wraps=comparison.SequenceMatcher) as matcher,
        ):
            entries = history.build_history(record)
        self.assertEqual(tuple(entry.revision.number for entry in entries), tuple(range(1, 101)))
        self.assertIsNone(entries[0].previous_number)
        self.assertFalse(entries[0].content_changed)
        self.assertEqual(tuple(entry.previous_number for entry in entries[1:]), tuple(range(1, 100)))
        self.assertTrue(all(entry.content_changed for entry in entries[1:]))
        self.assertEqual(compare.call_args_list,
                         [call(revisions[0], revisions[0])]
                         + [call(left, right) for left, right in zip(revisions, revisions[1:])])
        self.assertEqual(matcher.call_count, 300)
        self.assertEqual(record.history, tuple(reversed(revisions)))

    def test_101_snapshot_history_is_rejected_before_any_comparison(self):
        record = synthetic_record(*(synthetic_revision(number=index) for index in range(1, 102)))
        with (
            patch.object(history, "compare_revisions") as compare,
            patch.object(comparison, "SequenceMatcher") as matcher,
        ):
            with self.assertRaises(history.HistoryDataError) as raised:
                history.build_history(record)
            compare.assert_not_called()
            matcher.assert_not_called()
        self.assertEqual(str(raised.exception), "invalid_history")
