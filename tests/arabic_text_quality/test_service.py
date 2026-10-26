"""Independent synthetic Unicode, source identity, and comparison regressions."""

import hashlib
import json
import socket
import unicodedata
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from apps.arabic_text_quality.service import compare_texts, inspect_revision, inspect_text
from apps.fatwa_drafts.domain import Revision, State


def inspect(text, **kwargs):
    return inspect_text(text, synthetic_only=True, **kwargs)


def compare(before, after, **kwargs):
    return compare_texts(before, after, synthetic_only=True, **kwargs)


def findings(report, code):
    return [item for item in report.diagnostics if item.code == code]


class SourceQualityTests(unittest.TestCase):
    def assert_exact_locations(self, report):
        sources = {item.side: item.text for item in report.sources}
        for diagnostic in report.diagnostics:
            self.assertIn(diagnostic.severity, ("info", "warning", "error"))
            for location in (diagnostic.location, diagnostic.related_location):
                if location is None:
                    continue
                text = sources[location.side]
                self.assertGreaterEqual(location.start, 0)
                self.assertGreaterEqual(location.end, location.start)
                self.assertLessEqual(location.end, len(text))
                self.assertEqual(location.original, text[location.start : location.end])
                self.assertEqual(
                    location.codepoints,
                    tuple(f"U+{ord(char):04X}" for char in location.original),
                )
                self.assertGreaterEqual(location.line, 1)
                self.assertGreaterEqual(location.column, 1)

    def test_plain_arabic_and_vocalization_are_not_rewritten_or_warned(self):
        text = "\u0633\u0624\u0627\u0644 \u062a\u062c\u0631\u064a\u0628\u064a\u0651: \u0628\u064e\u0627\u0628"
        report = inspect(text)
        self.assertEqual(report.sources[0].text, text)
        self.assertEqual(report.sources[0].sha256, hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(report.sources[0].codepoint_length, len(text))
        self.assertFalse(findings(report, "control_character"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_empty_text_has_no_spurious_findings(self):
        self.assertEqual(inspect("").diagnostics, ())

    def test_codepoint_offsets_and_logical_columns_after_astral_and_crlf(self):
        report = inspect("\U0001f4bb\r\n\u0628\x00")
        diagnostic = findings(report, "control_character")[0]
        self.assertEqual(
            (
                diagnostic.location.start,
                diagnostic.location.end,
                diagnostic.location.line,
                diagnostic.location.column,
                diagnostic.location.end_line,
                diagnostic.location.end_column,
            ),
            (4, 5, 2, 2, 2, 3),
        )
        self.assertEqual(diagnostic.location.codepoints, ("U+0000",))
        self.assert_exact_locations(report)

    def test_embedded_c0_del_and_c1_controls_are_located(self):
        text = "a\x00b\x1bc\x7fd\x80e"
        report = inspect(text)
        controls = findings(report, "control_character")
        self.assertEqual([item.location.start for item in controls], [1, 3, 5, 7])
        self.assert_exact_locations(report)

    def test_ordinary_tabs_and_newlines_are_not_control_character_errors(self):
        report = inspect("a\tb\nc\r\nd")
        self.assertFalse(findings(report, "control_character"))

    def test_join_controls_are_conservative_and_preserved(self):
        text = "\u0628\u200c\u062a\u200d\u062b"
        report = inspect(text)
        controls = findings(report, "join_control")
        self.assertEqual([item.location.start for item in controls], [1, 3])
        self.assertTrue(all(item.severity == "info" for item in controls))
        self.assertEqual(report.sources[0].text, text)

    def test_bom_and_zero_width_space_are_visible_format_findings(self):
        report = inspect("\ufeffa\u200bb")
        self.assertEqual(
            [item.location.start for item in findings(report, "format_character")], [0, 2]
        )

    def test_bidi_override_is_reported_even_when_balanced(self):
        report = inspect("a\u202eb\u202cc")
        override = findings(report, "bidi_override")
        self.assertEqual(len(override), 1)
        self.assertEqual(override[0].location.codepoints, ("U+202E",))
        self.assertFalse(findings(report, "bidi_unmatched_closer"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_balanced_nested_isolates_and_embeddings_have_no_scope_anomaly(self):
        report = inspect("\u2067a\u202bb\u202cc\u2069")
        self.assertFalse(findings(report, "bidi_unmatched_closer"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_pop_directional_format_cannot_close_an_isolate(self):
        report = inspect("\u2067a\u202c")
        self.assertEqual(findings(report, "bidi_unmatched_closer")[0].location.start, 2)
        self.assertEqual(findings(report, "bidi_unclosed_scope")[0].location.start, 0)

    def test_isolate_pop_implicitly_closes_nested_embeddings(self):
        report = inspect("\u2067\u202ba\u2069")
        self.assertFalse(findings(report, "bidi_unmatched_closer"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_nested_isolate_indexes_survive_embedding_pops(self):
        report = inspect("\u202b\u2067\u202b\u2066\u202aX\u2069\u202c\u2069\u202c")
        self.assertFalse(findings(report, "bidi_unmatched_closer"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))
        self.assert_exact_locations(report)

    def test_unmatched_isolate_pops_do_not_consume_embedding_scopes(self):
        report = inspect("\u202b" * 100 + "\u2069" * 100 + "\u202c" * 100)
        self.assertEqual(len(findings(report, "bidi_unmatched_closer")), 100)
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_paragraph_boundary_does_not_allow_later_closer_to_match(self):
        for separator in ("\n", "\r\n", "\u2029", "\x85"):
            with self.subTest(separator=ascii(separator)):
                report = inspect("\u2067a" + separator + "b\u2069")
                self.assertEqual(len(findings(report, "bidi_unclosed_scope")), 1)
                self.assertEqual(len(findings(report, "bidi_unmatched_closer")), 1)

    def test_unicode_line_separator_does_not_reset_bidi_paragraph(self):
        report = inspect("\u2067a\u2028b\u2069")
        self.assertFalse(findings(report, "bidi_unmatched_closer"))
        self.assertFalse(findings(report, "bidi_unclosed_scope"))

    def test_mixed_and_unusual_line_endings_are_detected(self):
        report = inspect("a\r\nb\nc\rd\u2028e\u2029f\x85g")
        self.assertTrue(findings(report, "mixed_line_endings"))
        self.assertTrue(findings(report, "unusual_line_ending"))
        self.assert_exact_locations(report)

    def test_consistent_crlf_is_not_mixed(self):
        self.assertFalse(findings(inspect("a\r\nb\r\n"), "mixed_line_endings"))

    def test_nfc_arabic_combining_and_hangul_differences_keep_original_span(self):
        for value, offset, changed in (
            ("\u0627\u0654", 1, "\u0627\u0654"),
            ("\u1100\u1161", 1, "\u1100\u1161"),
            ("q\u0307\u0323", 2, "\u0307\u0323"),
        ):
            with self.subTest(value=ascii(value)):
                text = "[" + value + "]"
                report = inspect(text)
                diagnostic = findings(report, "normalization_nfc")[0]
                self.assertEqual(diagnostic.location.original, changed)
                self.assertEqual(diagnostic.location.start, offset)
                self.assertEqual(diagnostic.location.end, 1 + len(value))
                self.assertEqual(report.sources[0].text, text)
                self.assert_exact_locations(report)

    def test_compatibility_ligature_has_nfkc_difference_without_canonical_claim(self):
        report = inspect("\ufefb")
        self.assertTrue(findings(report, "normalization_nfkc"))
        self.assertFalse(findings(report, "normalization_nfc"))
        self.assertEqual(report.sources[0].text, "\ufefb")

    def test_whitespace_findings_retain_exact_runs(self):
        report = inspect("  a\t b  \n\u00a0c")
        for code in (
            "leading_whitespace",
            "trailing_whitespace",
            "repeated_whitespace",
            "unusual_whitespace",
        ):
            with self.subTest(code=code):
                self.assertTrue(findings(report, code))
        self.assert_exact_locations(report)

    def test_reports_are_frozen_deterministic_and_ascii_serializable(self):
        report = inspect("\u0628\x1b\u202e\r\n \ufefb")
        self.assertEqual(report, inspect(report.sources[0].text))
        serialized = report.to_json()
        self.assertTrue(serialized.isascii())
        self.assertNotIn("\x1b", serialized)
        self.assertNotIn("\u202e", serialized)
        self.assertEqual(json.loads(serialized), report.to_dict())
        self.assertEqual(report.to_dict()["unicode_version"], unicodedata.unidata_version)
        self.assertTrue(report.to_dict()["source_preserved"])
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            report.sources[0].text = "altered"

    def test_synthetic_guard_requires_literal_true(self):
        for value in (False, None, 0, 1, "true"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    inspect_text("synthetic", synthetic_only=value)
                with self.assertRaises(ValueError):
                    compare_texts("before", "after", synthetic_only=value)

    def test_invalid_kind_is_rejected(self):
        for kind in ("approval", "private", None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                inspect("synthetic", kind=kind)

    def test_invalid_text_and_surrogates_rejected_on_each_side(self):
        for bad in (None, 4, b"text", "\ud800", "\udfff", "\ud83d\udcbb", "x" * 10001):
            with self.subTest(value=repr(bad)[:30]):
                with self.assertRaises((ValueError, TypeError)):
                    inspect(bad)
                with self.assertRaises((ValueError, TypeError)):
                    compare(bad, "valid")
                with self.assertRaises((ValueError, TypeError)):
                    compare("valid", bad)

    def test_exact_maximum_codepoint_limit_accepts_astral_scalars(self):
        text = "\U0001f4bb" * 10000
        self.assertEqual(inspect(text).sources[0].text, text)

    def test_services_need_no_network_files_or_framework_runtime(self):
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network")),
            patch("builtins.open", side_effect=AssertionError("filesystem")),
        ):
            first = inspect("Synthetic question")
            second = compare("Synthetic text", "Synthetic  text")
        self.assertTrue(first.sources)
        self.assertTrue(second.diagnostics)


class ComparisonQualityTests(unittest.TestCase):
    assert_exact_locations = SourceQualityTests.assert_exact_locations

    def test_inserted_deleted_and_replaced_whitespace_has_paired_exact_locations(self):
        for before, after in (
            ("ab", "a b"),
            ("a b", "ab"),
            ("a b", "a\tb"),
            ("a b", "a\u00a0b"),
            (" a ", "a"),
        ):
            with self.subTest(before=before, after=after):
                report = compare(before, after)
                diagnostics = findings(report, "whitespace_change")
                self.assertTrue(diagnostics)
                self.assertTrue(all(item.related_location is not None for item in diagnostics))
                self.assert_exact_locations(report)
                self.assertEqual(tuple(item.text for item in report.sources), (before, after))

    def test_line_ending_conversion_is_reported_as_an_exact_change(self):
        report = compare("a\r\nb\r\n", "a\nb\n")
        self.assertTrue(findings(report, "line_ending_change"))
        self.assert_exact_locations(report)

    def test_normalization_only_change_and_sources_remain_distinct(self):
        before, after = "\u0627\u0654", "\u0623"
        report = compare(before, after)
        self.assertTrue(findings(report, "normalization_only_change"))
        self.assertNotEqual(report.sources[0].sha256, report.sources[1].sha256)
        self.assert_exact_locations(report)

    def test_substantive_replacement_is_not_falsely_whitespace_only(self):
        report = compare("alpha", "beta")
        self.assertFalse(findings(report, "whitespace_change"))
        self.assertFalse(findings(report, "normalization_only_change"))

    def test_unchanged_text_has_no_change_diagnostics(self):
        text = "a\r\n\u202e b\u202c"
        report = compare(text, text)
        for code in ("whitespace_change", "line_ending_change", "normalization_only_change"):
            self.assertFalse(findings(report, code))

    def test_normalization_does_not_conflate_unrelated_content_changes(self):
        report = compare("\u0627\u0654x", "\u0623y")
        self.assertFalse(findings(report, "normalization_only_change"))

    def test_comparison_is_deterministic_in_both_directions(self):
        before, after = "ab ab\r\n\u0627\u0654", "ab  ab\n\u0623"
        for left, right in ((before, after), (after, before)):
            with self.subTest(left=left):
                report = compare(left, right)
                self.assertEqual(report.to_json(), compare(left, right).to_json())
                self.assert_exact_locations(report)


class RevisionQualityTests(unittest.TestCase):
    assert_exact_locations = SourceQualityTests.assert_exact_locations

    def revision(self):
        return Revision(
            number=1,
            action="synthetic_snapshot",
            human_editor="Synthetic editor",
            editorial_note="Synthetic quality test",
            state=State.PREPARATION,
            title="Synthetic\x00 title",
            answer="\u0627\u0654\r\n",
            reference_links=(),
            reviewer_notes="  synthetic notes ",
        )

    def test_revision_adapter_checks_all_fields_without_mutating_snapshot(self):
        revision = self.revision()
        original = replace(revision)
        report = inspect_revision(revision, synthetic_only=True)
        self.assertEqual(revision, original)
        self.assertEqual(
            {source.side: source.text for source in report.sources},
            {
                "source." + key: getattr(revision, key)
                for key in ("title", "answer", "reviewer_notes")
            },
        )
        self.assert_exact_locations(report)

    def test_revision_pair_uses_authoritative_comparison_service(self):
        from apps.revision_core import revision_comparison

        before = self.revision()
        after = replace(before, number=2, answer="\u0623\r\n", reviewer_notes="synthetic notes")
        with patch.object(
            revision_comparison, "compare_revisions", wraps=revision_comparison.compare_revisions
        ) as authoritative:
            report = inspect_revision(after, previous=before, synthetic_only=True)
        authoritative.assert_called_once_with(before, after)
        self.assertEqual(len(report.sources), 6)
        self.assertTrue(findings(report, "normalization_only_change"))
        self.assertTrue(findings(report, "whitespace_change"))
        self.assert_exact_locations(report)

    def test_revision_guards_reject_bad_prior_and_current_inputs(self):
        revision = self.revision()
        for bad in (False, 0, "", object()):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    inspect_revision(bad, synthetic_only=True)
                with self.assertRaises((ValueError, TypeError)):
                    inspect_revision(revision, previous=bad, synthetic_only=True)
        with self.assertRaises(ValueError):
            inspect_revision(revision)
