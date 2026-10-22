"""Read-only audit over invented fixtures; no real attribution or scholarly content."""

import socket
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from functools import partial
from unittest.mock import patch

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.editorial_demo.revision_history import HistoryDataError
from apps.fatwa_drafts.domain import State
from apps.fatwa_drafts.intake import serialize_intake


class RevisionAuditTests(unittest.TestCase):
    def setUp(self):
        from apps.fatwa_drafts.revision_audit import build_revision_audit

        self.build = partial(build_revision_audit, synthetic_fixtures_only=True)
        self.record = REVISION_HISTORY_RECORD

    def test_numbers_resolve_original_snapshots_including_gaps_and_shuffled_history(self):
        record = replace(self.record, history=self.record.history[::-1])
        summary = self.build(record)

        self.assertIs(summary.record, record)
        self.assertEqual([entry.revision.number for entry in summary.entries], [1, 2, 4, 7, 9, 11])
        self.assertEqual(
            [entry.history_entry.previous_number for entry in summary.entries],
            [None, 1, 2, 4, 7, 9],
        )
        self.assertIsNone(summary.entries[0].previous_revision)
        for index, entry in enumerate(summary.entries):
            self.assertIs(entry.revision, self.record.history[index])
            if index:
                self.assertIs(entry.previous_revision, self.record.history[index - 1])
        self.assertEqual(record.history[0].number, 11)

    def test_content_and_reference_summaries_are_retained(self):
        rows = {entry.revision.number: entry for entry in self.build(self.record).entries}

        self.assertEqual(
            rows[2].history_entry.changed_fields,
            ("العنوان", "نص المسودة — حقل التحرير البشري", "ملاحظات المراجع"),
        )
        self.assertEqual(rows[2].history_entry.references_added, 1)
        self.assertEqual(rows[2].history_entry.references_removed, 1)
        self.assertEqual(rows[7].history_entry.changed_fields, ())
        self.assertTrue(rows[7].history_entry.references_changed)
        self.assertEqual(rows[7].history_entry.reference_positions_changed, 2)
        self.assertEqual(rows[9].history_entry.references_added, 1)
        self.assertEqual(rows[9].history_entry.reference_positions_changed, 1)
        self.assertFalse(rows[11].history_entry.content_changed)
        self.assertEqual(rows[11].changed_metadata, ("action", "human_editor", "editorial_note"))

    def test_transitions_are_observed_state_differences_not_inferred_from_action(self):
        first = self.record.history[0]
        second = replace(first, number=4, state=State.READY)
        third = replace(second, number=9, action="transition")
        summary = self.build(replace(self.record, history=(third, first, second)))
        initial, moved, unchanged = summary.entries

        self.assertIsNone(initial.observed_state_change)
        self.assertEqual(initial.changed_metadata, ())
        self.assertEqual(moved.observed_state_change, (State.PREPARATION, State.READY))
        self.assertEqual(moved.changed_metadata, ("state",))
        self.assertEqual(moved.revision.action, "synthetic_snapshot")
        self.assertIsNone(unchanged.observed_state_change)
        self.assertEqual(unchanged.changed_metadata, ("action",))

    def test_human_labels_and_notes_compare_exact_unicode_and_whitespace(self):
        first = replace(
            self.record.history[0],
            human_editor="  أ\tوسم اصطناعي\n",
            editorial_note="\tملاحظة اصطناعية\r\n ",
        )
        second = replace(
            first,
            number=5,
            human_editor="  ا\u0654\tوسم اصطناعي\n",
            editorial_note="\tملاحظة اصطناعية\n ",
        )
        initial, changed = self.build(replace(self.record, history=(first, second))).entries

        self.assertEqual(initial.changed_metadata, ())
        self.assertEqual(changed.changed_metadata, ("human_editor", "editorial_note"))
        self.assertEqual(changed.revision.human_editor, "  ا\u0654\tوسم اصطناعي\n")
        self.assertEqual(changed.previous_revision.human_editor, "  أ\tوسم اصطناعي\n")
        self.assertEqual(changed.revision.editorial_note, "\tملاحظة اصطناعية\n ")
        self.assertFalse(changed.history_entry.content_changed)
        self.assertIsNone(changed.observed_state_change)

    def test_only_the_number_changes_without_fabricated_metadata_or_content_changes(self):
        first = self.record.history[0]
        second = replace(first, number=27)
        rows = self.build(replace(self.record, history=(first, second))).entries

        self.assertEqual(rows[1].revision.number, 27)
        self.assertEqual(rows[1].changed_metadata, ())
        self.assertFalse(rows[1].history_entry.content_changed)
        self.assertIsNone(rows[1].observed_state_change)

    def test_reference_identity_changes_remain_visible_with_same_source_id(self):
        first = self.record.history[0]
        original = first.reference_links[0]
        changed = replace(original, edition_key="SYN-DIFFERENT-EDITION")
        second = replace(first, number=3, reference_links=(changed, first.reference_links[1]))
        row = self.build(replace(self.record, history=(first, second))).entries[1]

        self.assertTrue(row.history_entry.references_changed)
        self.assertEqual(row.history_entry.references_added, 1)
        self.assertEqual(row.history_entry.references_removed, 1)
        self.assertIs(row.previous_revision.reference_links[0], original)
        self.assertIs(row.revision.reference_links[0], changed)
        self.assertEqual(row.revision.reference_links[0].source_id, original.source_id)

    def test_summary_is_deterministic_immutable_and_preserves_every_source_value(self):
        before = asdict(self.record)
        source_bytes = serialize_intake((self.record.intake,))
        summary = self.build(self.record)

        self.assertEqual(summary, self.build(self.record))
        self.assertEqual(asdict(self.record), before)
        self.assertEqual(serialize_intake((self.record.intake,)), source_bytes)
        self.assertIs(summary.record.intake, self.record.intake)
        self.assertEqual(
            summary.record.intake.question,
            "  سجل مصدر اصطناعي ثابت.\nلا يتضمن سؤالًا فقهيًا.  ",
        )
        self.assertEqual(
            summary.entries[0].revision.answer,
            "  نص اختبار تحريري فقط.\r\n\tموضع تجريبي للمراجعة.\n",
        )
        self.assertEqual(
            [ref.source_id for ref in summary.entries[3].revision.reference_links],
            ["SYN-ADD", "SYN-KEEP"],
        )
        for source, row in zip(self.record.history, summary.entries, strict=True):
            self.assertIs(row.revision.reference_links, source.reference_links)
            self.assertEqual(asdict(row.revision), asdict(source))
        with self.assertRaises(FrozenInstanceError):
            summary.entries = ()
        with self.assertRaises(FrozenInstanceError):
            summary.entries[0].changed_metadata = ("state",)

    def test_ambiguous_or_invalid_history_is_rejected_without_changing_source(self):
        first = self.record.history[0]
        for history in ((), (first, first), (replace(first, number=True),)):
            record = replace(self.record, history=history)
            before = asdict(record)
            with self.subTest(history=history), self.assertRaises(HistoryDataError):
                self.build(record)
            self.assertEqual(asdict(record), before)

    def test_invalid_state_does_not_become_an_audit_transition(self):
        for state in ("draft_preparation", "published", None, True):
            revision = replace(self.record.history[0], state=state)
            with self.subTest(state=state), self.assertRaisesRegex(
                HistoryDataError, "^invalid_history_state$"
            ):
                self.build(replace(self.record, history=(revision,)))

    def test_existing_comparison_bound_remains_explicit(self):
        revision = replace(self.record.history[0], answer="x" * 10001)
        with self.assertRaisesRegex(HistoryDataError, "^invalid_history_content$"):
            self.build(replace(self.record, history=(revision,)))

    def test_synthetic_acknowledgement_is_explicit_and_requires_literal_true(self):
        from apps.fatwa_drafts.revision_audit import build_revision_audit

        with self.assertRaisesRegex(
            HistoryDataError, "^audit: synthetic_fixture_acknowledgement_required$"
        ):
            build_revision_audit(self.record)
        for acknowledgement in (False, None, 1, "true"):
            with self.subTest(acknowledgement=acknowledgement), self.assertRaisesRegex(
                HistoryDataError, "^audit: synthetic_fixture_acknowledgement_required$"
            ):
                build_revision_audit(self.record, synthetic_fixtures_only=acknowledgement)

    def test_summary_has_no_file_network_or_database_side_effects(self):
        before = set(sys.modules)
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network access")),
            patch("builtins.open", side_effect=AssertionError("file access")),
        ):
            summary = self.build(self.record)
        self.assertEqual(len(summary.entries), 6)
        self.assertFalse(
            any(name.startswith(("django.db", "psycopg")) for name in set(sys.modules) - before)
        )


if __name__ == "__main__":
    unittest.main()
