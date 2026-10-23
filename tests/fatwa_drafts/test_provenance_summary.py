"""D2-SYN-PROVENANCE-01: invented labels and source pointers, no real case data."""

import importlib
import socket
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import patch

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink, serialize_intake
from apps.revision_core.revision_history import HistoryDataError


def synthetic_record():
    """Seven numbered observations with hand-checked change categories."""
    first_ref = ReferenceLink("SYN-D2", "SYN-BOOK", "SYN-ED", "a" * 64, "b" * 64, "A")
    second_ref = replace(first_ref, source_id="B")
    intake = IntakeItem(
        "D2-SYN-PROVENANCE-01", "  سؤال اختبار اصطناعي\r\n", "https://example.invalid/d2",
        reference_links=(first_ref, second_ref),
    )
    first = Revision(
        2, "synthetic_observation", "\tأ\n", "synthetic note", State.PREPARATION,
        "synthetic title", "synthetic text", intake.reference_links, "",
    )
    content = replace(first, number=5, title="changed synthetic title")
    metadata = replace(content, number=9, human_editor="\tا\u0654\n")
    both = replace(
        metadata, number=14, state=State.READY, editorial_note="different synthetic note",
        reference_links=(second_ref, first_ref),
    )
    unchanged = replace(both, number=20)
    return_state = replace(unchanged, number=31, state=State.PREPARATION, action="transition")
    repeated_state_pair = replace(return_state, number=50, state=State.READY)
    return DraftRecord(
        intake, (first, content, metadata, both, unchanged, return_state, repeated_state_pair)
    )


class ProvenanceSummaryTests(unittest.TestCase):
    def setUp(self):
        try:
            module = importlib.import_module("apps.fatwa_drafts.revision_provenance_summary")
        except ModuleNotFoundError:
            self.fail("the provenance aggregate API has not been implemented")
        self.build = module.build_revision_provenance_summary
        self.record = synthetic_record()

    def summarize(self, record=None):
        return self.build(record or self.record, synthetic_fixtures_only=True)

    def test_change_counts_partition_only_adjacent_observations(self):
        summary = self.summarize()
        self.assertEqual(summary.snapshot_count, 7)
        self.assertEqual(summary.comparison_count, 6)
        self.assertEqual(summary.content_only_count, 1)
        self.assertEqual(summary.metadata_only_count, 3)
        self.assertEqual(summary.content_and_metadata_count, 1)
        self.assertEqual(summary.unchanged_count, 1)
        self.assertEqual(
            summary.metadata_change_frequencies,
            (("action", 1), ("human_editor", 1), ("editorial_note", 1), ("state", 3)),
        )

    def test_single_snapshot_has_attribution_but_no_comparison(self):
        summary = self.summarize(replace(self.record, history=self.record.history[:1]))
        self.assertEqual(summary.snapshot_count, 1)
        self.assertEqual(summary.comparison_count, 0)
        self.assertEqual(
            (summary.content_only_count, summary.metadata_only_count,
             summary.content_and_metadata_count, summary.unchanged_count),
            (0, 0, 0, 0),
        )
        self.assertEqual(
            summary.metadata_change_frequencies,
            (("action", 0), ("human_editor", 0), ("editorial_note", 0), ("state", 0)),
        )
        self.assertEqual(summary.attributions[0].snapshot_count, 1)
        self.assertEqual(summary.observed_state_changes, ())

    def test_exact_unicode_attribution_groups_preserve_first_observed_order(self):
        summary = self.summarize()
        self.assertEqual(
            [(group.label, group.snapshot_count) for group in summary.attributions],
            [("\tأ\n", 2), ("\tا\u0654\n", 5)],
        )
        self.assertEqual(
            [[entry.revision.number for entry in group.entries] for group in summary.attributions],
            [[2, 5], [9, 14, 20, 31, 50]],
        )
        spaced = replace(self.record.history[-1], number=80, human_editor=" أ ")
        expanded = self.summarize(replace(self.record, history=(*self.record.history, spaced)))
        self.assertEqual(expanded.attributions[-1].label, " أ ")
        self.assertEqual(expanded.attributions[-1].snapshot_count, 1)

    def test_state_pairs_count_observations_without_interpreting_action_labels(self):
        summary = self.summarize()
        self.assertEqual(
            [(group.before, group.after, group.observation_count)
             for group in summary.observed_state_changes],
            [(State.PREPARATION, State.READY, 2), (State.READY, State.PREPARATION, 1)],
        )
        self.assertEqual(
            [[entry.revision.number for entry in group.entries]
             for group in summary.observed_state_changes],
            [[14, 50], [31]],
        )
        # A stored pair is observable even when domain transition rules disallow it.
        first = replace(self.record.history[0], state=State.RECEIVED, action="transition")
        second = replace(first, number=10, state=State.READY)
        third = replace(second, number=19)
        observed = self.summarize(replace(self.record, history=(first, second, third)))
        self.assertEqual(observed.observed_state_changes[0].observation_count, 1)
        self.assertEqual(observed.unchanged_count, 1)

    def test_shuffled_gapped_history_has_deterministic_summary_and_original_identities(self):
        shuffled = replace(self.record, history=self.record.history[::-1])
        summary = self.summarize(shuffled)
        self.assertIs(summary.audit.record, shuffled)
        self.assertEqual([row.revision.number for row in summary.audit.entries], [2, 5, 9, 14, 20, 31, 50])
        self.assertEqual(summary, self.summarize(shuffled))
        self.assertEqual(summary.metadata_change_frequencies, self.summarize().metadata_change_frequencies)
        for group in (*summary.attributions, *summary.observed_state_changes):
            for entry in group.entries:
                self.assertTrue(any(entry is original for original in summary.audit.entries))
        for entry, original in zip(summary.audit.entries, self.record.history, strict=True):
            self.assertIs(entry.revision, original)
            self.assertIs(entry.revision.reference_links, original.reference_links)
        self.assertIs(summary.audit.record.intake, shuffled.intake)
        self.assertIs(summary.audit.entries[0].revision.reference_links[0], shuffled.intake.reference_links[0])

    def test_summary_is_frozen_and_does_not_modify_any_source_value(self):
        before = asdict(self.record)
        source_bytes = serialize_intake((self.record.intake,))
        summary = self.summarize()
        self.assertEqual(asdict(self.record), before)
        self.assertEqual(serialize_intake((self.record.intake,)), source_bytes)
        with self.assertRaises(FrozenInstanceError):
            summary.metadata_only_count = 99
        with self.assertRaises(FrozenInstanceError):
            summary.attributions[0].label = "changed"
        with self.assertRaises(FrozenInstanceError):
            summary.observed_state_changes[0].before = State.READY
        self.assertIsInstance(summary.metadata_change_frequencies, tuple)
        self.assertIsInstance(summary.attributions, tuple)
        self.assertIsInstance(summary.observed_state_changes, tuple)

    def test_acknowledgement_requires_literal_true_before_processing_input(self):
        with self.assertRaisesRegex(HistoryDataError, "synthetic_fixture_acknowledgement_required"):
            self.build(None)
        for acknowledgement in (False, None, 1, "true", [True]):
            with self.subTest(acknowledgement=acknowledgement), self.assertRaisesRegex(
                HistoryDataError, "synthetic_fixture_acknowledgement_required"
            ):
                self.build(None, synthetic_fixtures_only=acknowledgement)

    def test_existing_audit_identity_and_content_bounds_remain_enforced(self):
        first = self.record.history[0]
        accepted = replace(
            self.record,
            history=tuple(replace(first, number=index) for index in range(1, 101)),
        )
        summary = self.summarize(accepted)
        self.assertEqual((summary.snapshot_count, summary.unchanged_count), (100, 99))
        boundary_text = "".join(chr(0x1000 + index) for index in range(10000))
        boundary = self.summarize(replace(
            self.record, history=(replace(first, answer=boundary_text),)
        ))
        self.assertEqual(boundary.snapshot_count, 1)
        for history in (
            (), (first, first), (replace(first, number=True),),
            (*accepted.history, replace(first, number=101)),
            (replace(first, answer="x" * 10001),),
            (replace(first, human_editor="x" * 201),),
            (replace(first, state="published"),),
        ):
            with self.subTest(history_length=len(history)), self.assertRaises(HistoryDataError):
                self.summarize(replace(self.record, history=history))

    def test_building_summary_uses_no_file_network_or_database_access(self):
        before = set(sys.modules)
        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch.object(socket, "socket", side_effect=AssertionError("network access")),
        ):
            summary = self.summarize()
        self.assertEqual(summary.comparison_count, 6)
        self.assertFalse(
            any(name.startswith(("django", "psycopg", "apps.editorial_demo"))
                for name in set(sys.modules) - before)
        )


if __name__ == "__main__":
    unittest.main()
