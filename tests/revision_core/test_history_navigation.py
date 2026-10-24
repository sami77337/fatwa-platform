"""Pure snapshot navigation keeps revision identities distinct from offsets."""

import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink
from apps.revision_core import revision_history as history


class HistoryNavigationTests(unittest.TestCase):
    def setUp(self):
        reference = ReferenceLink("synthetic", "622", "synthetic", "a" * 64, "b" * 64, "7")
        self.first = Revision(
            2, "synthetic_snapshot", "Synthetic editor", "Synthetic note", State.PREPARATION,
            "أ", " \t\r\nا\u0654 \u200f", (reference,), "Synthetic notes",
        )
        self.middle = replace(self.first, number=17)
        self.last = replace(self.first, number=999999, title="ا\u0654")
        self.record = DraftRecord(
            IntakeItem("SYN-NAVIGATION", "Synthetic input", "https://example.invalid/synthetic"),
            (self.last, self.first, self.middle),
        )

    def test_selects_gapped_middle_identity_and_chronological_neighbors(self):
        self.assertTrue(callable(getattr(history, "navigate_history", None)))
        result = history.navigate_history(self.record, "17")
        self.assertIs(result.selected, self.middle)
        self.assertIs(result.previous, self.first)
        self.assertIs(result.next, self.last)

    def test_first_and_last_have_only_the_available_neighbor(self):
        first = history.navigate_history(self.record, "2")
        last = history.navigate_history(self.record, "999999")
        self.assertIs(first.selected, self.first)
        self.assertIsNone(first.previous)
        self.assertIs(first.next, self.middle)
        self.assertIs(last.selected, self.last)
        self.assertIs(last.previous, self.middle)
        self.assertIsNone(last.next)

    def test_single_snapshot_and_repeated_same_selection_do_not_invent_neighbors(self):
        record = replace(self.record, history=(self.middle,))
        first = history.navigate_history(record, "17")
        second = history.navigate_history(record, "17")
        self.assertIs(first.selected, self.middle)
        self.assertIsNone(first.previous)
        self.assertIsNone(first.next)
        self.assertEqual(second, first)
        self.assertIs(second.selected, first.selected)

    def test_unchanged_content_is_still_a_navigable_snapshot(self):
        result = history.navigate_history(self.record, "2")
        self.assertIs(result.next, self.middle)
        self.assertEqual(result.next.answer, self.first.answer)
        self.assertEqual(result.next.reference_links, self.first.reference_links)

    def test_result_is_immutable_and_original_unicode_and_sources_are_retained(self):
        original = asdict(self.record)
        result = history.navigate_history(self.record, "17")
        self.assertEqual(result.selected.answer, " \t\r\nا\u0654 \u200f")
        self.assertEqual(result.previous.title, "أ")
        self.assertEqual(result.next.title, "ا\u0654")
        self.assertIs(result.selected.reference_links, self.middle.reference_links)
        self.assertEqual(asdict(self.record), original)
        with self.assertRaises(FrozenInstanceError):
            result.selected = self.last

    def test_all_history_permutations_give_the_same_identity_neighbors(self):
        from itertools import permutations

        for revisions in permutations(self.record.history):
            with self.subTest(numbers=tuple(revision.number for revision in revisions)):
                result = history.navigate_history(replace(self.record, history=revisions), "17")
                self.assertIs(result.selected, self.middle)
                self.assertIs(result.previous, self.first)
                self.assertIs(result.next, self.last)

    def test_invalid_or_missing_identifiers_keep_the_selection_error(self):
        for selected in (None, 17, True, "", "0", "017", " 17", "17\n", "١٧", "１７",
                         "+17", "1.7", "1000000", "\ud800"):
            with self.subTest(selected=repr(selected)):
                with self.assertRaises(history.InvalidRevisionId) as raised:
                    history.navigate_history(self.record, selected)
                self.assertEqual(str(raised.exception), "invalid_or_missing_revision_identity")
                self.assertIsNone(raised.exception.__cause__)

    def test_unknown_identity_is_not_interpreted_as_a_position(self):
        for selected in ("1", "3", "18"):
            with self.subTest(selected=selected):
                with self.assertRaises(history.UnknownRevisionId) as raised:
                    history.navigate_history(self.record, selected)
                self.assertEqual(str(raised.exception), "unknown_revision_identity")
                self.assertIsInstance(raised.exception.__cause__, KeyError)
                self.assertEqual(raised.exception.__cause__.args, (selected,))

    def test_invalid_unselected_snapshot_is_validated_before_selection(self):
        cases = (
            ((), "invalid_history", None),
            ((self.first, self.first), "invalid_or_duplicate_revision_identity", None),
            ((replace(self.first, number=True),),
             "invalid_or_duplicate_revision_identity", None),
            ((self.first, replace(self.last, answer="x" * 10001)),
             "invalid_history_content", "comparison_text_invalid_or_too_long"),
            ((self.first, replace(self.last, answer="\ud800")),
             "invalid_history_content", "comparison_text_invalid_unicode"),
            ((self.first, replace(self.last, action="")),
             "invalid_history_content", "history.action: required_or_control_character"),
        )
        for revisions, message, cause in cases:
            with self.subTest(message=message, cause=cause):
                with self.assertRaises(history.HistoryDataError) as raised:
                    history.navigate_history(replace(self.record, history=revisions), None)
                self.assertEqual(str(raised.exception), message)
                if cause is None:
                    self.assertIsNone(raised.exception.__cause__)
                else:
                    self.assertIsInstance(raised.exception.__cause__, ValueError)
                    self.assertEqual(str(raised.exception.__cause__), cause)

    def test_accepts_one_hundred_snapshots_and_rejects_one_hundred_and_one(self):
        revisions = tuple(replace(self.first, number=number) for number in range(1, 101))
        result = history.navigate_history(replace(self.record, history=revisions[::-1]), "99")
        self.assertIs(result.previous, revisions[97])
        self.assertIs(result.selected, revisions[98])
        self.assertIs(result.next, revisions[99])
        oversized = (*revisions, replace(self.first, number=101))
        with self.assertRaisesRegex(history.HistoryDataError, "^invalid_history$"):
            history.navigate_history(replace(self.record, history=oversized), "99")

    def test_real_navigation_runs_without_editorial_framework_or_io_dependencies(self):
        script = """
import importlib.abc
import socket
import sys
from unittest.mock import patch

blocked = ('apps.editorial_demo', 'django', 'psycopg', 'psycopg2')

class RejectDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == root or fullname.startswith(root + '.') for root in blocked):
            raise AssertionError('Forbidden dependency: ' + fullname)
        return None

sys.meta_path.insert(0, RejectDependency())
from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem
from apps.revision_core.revision_history import navigate_history

revision = Revision(7, 'synthetic_snapshot', 'Synthetic editor', 'Synthetic note',
                    State.PREPARATION, 'Synthetic title', 'Synthetic answer', (), '')
record = DraftRecord(IntakeItem('SYN-COLD-NAV', 'Synthetic input',
                                'https://example.invalid/synthetic'), (revision,))
with patch.object(socket, 'socket', side_effect=AssertionError('network')), \\
        patch('builtins.open', side_effect=AssertionError('file access')):
    result = navigate_history(record, '7')
    assert result.selected is revision
    assert result.previous is None and result.next is None
assert not any(name == root or name.startswith(root + '.')
               for name in sys.modules for root in blocked)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
