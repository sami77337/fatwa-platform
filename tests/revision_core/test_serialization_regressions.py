"""Trusted synthetic object graphs survive the neutral-core compatibility move."""

import base64
import copy
import os
import pickle
import subprocess
import sys
import textwrap
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink
from apps.fatwa_drafts.revision_audit import build_revision_audit
from apps.revision_core.revision_comparison import compare_revisions
from apps.revision_core.revision_history import build_history, select_revisions


def synthetic_graph():
    """Share source objects deliberately; keep an equal-but-distinct pointer too."""
    reference = ReferenceLink("synthetic", "SYN-BOOK", "SYN-EDITION", "a" * 64, "b" * 64, "7")
    intake = IntakeItem(
        "SYN-SERIALIZATION",
        "Synthetic technical question.",
        "https://example.invalid/synthetic",
        reference_links=(reference,),
    )
    before = Revision(
        2,
        "synthetic_snapshot",
        "Synthetic editor",
        "Synthetic note",
        State.PREPARATION,
        "أ",
        " \t\r\n ",
        (reference,),
        "Synthetic notes",
    )
    after = replace(before, number=9, title="ا\u0654", answer=" \t\n ")
    record = DraftRecord(intake, (before, after))
    history = build_history(record)
    return {
        "record": record,
        "sibling": DraftRecord(intake, (before,)),
        "history": history,
        "comparison": compare_revisions(before, after),
        "audit": build_revision_audit(record, synthetic_fixtures_only=True),
        "selection": select_revisions(history, "2", "9"),
        "reference": reference,
        "equal_reference": replace(reference),
        "repeated_record": record,
    }


class SerializationGraphTests(unittest.TestCase):
    def assert_graph_contract(self, restored, original):
        self.assertEqual(restored, original)
        record = restored["record"]
        before, after = record.history
        self.assertIsNot(record, original["record"])
        self.assertIsNot(record.intake, original["record"].intake)
        self.assertIsNot(before, original["record"].history[0])
        self.assertIs(restored["repeated_record"], record)
        self.assertIs(restored["sibling"].intake, record.intake)
        self.assertIs(restored["sibling"].current, before)
        self.assertIs(restored["history"][0].revision, before)
        self.assertIs(restored["history"][1].revision, after)
        self.assertIs(restored["selection"][0], before)
        self.assertIs(restored["selection"][1], after)
        audit = restored["audit"]
        self.assertIs(audit.record, record)
        self.assertIs(audit.entries[0].revision, before)
        self.assertIs(audit.entries[1].revision, after)
        self.assertIsNone(audit.entries[0].previous_revision)
        self.assertIs(audit.entries[1].previous_revision, before)
        reference = restored["reference"]
        self.assertIsNot(reference, original["reference"])
        self.assertIs(record.intake.reference_links[0], reference)
        self.assertIs(before.reference_links[0], reference)
        self.assertIs(after.reference_links[0], reference)
        comparison = restored["comparison"]
        self.assertIs(comparison.before_references[0].reference, reference)
        self.assertIs(comparison.after_references[0].reference, reference)
        self.assertEqual(restored["equal_reference"], reference)
        self.assertIsNot(restored["equal_reference"], reference)
        self.assertIs(before.state, State.PREPARATION)
        self.assertIs(after.state, State.PREPARATION)
        self.assertEqual([entry.revision.number for entry in restored["history"]], [2, 9])
        self.assertEqual(comparison.targets[0].anchor, "change-title")
        self.assertEqual(comparison.targets[1].anchor, "change-answer")
        self.assertEqual("".join(part.text for part in comparison.fields[0].before), "أ")
        self.assertEqual("".join(part.text for part in comparison.fields[0].after), "ا\u0654")
        self.assertEqual("".join(part.text for part in comparison.fields[1].before), " \t\r\n ")
        self.assertEqual("".join(part.text for part in comparison.fields[1].after), " \t\n ")

    def assert_graph_frozen(self, graph):
        cases = (
            (graph["record"], "history", ()),
            (graph["record"].intake, "question", "changed"),
            (graph["record"].current, "title", "changed"),
            (graph["reference"], "source_id", "changed"),
            (graph["history"][0], "previous_number", 99),
            (graph["comparison"], "targets", ()),
            (graph["comparison"].fields[0].before[0], "text", "changed"),
            (graph["comparison"].before_references[0], "position", 99),
            (graph["audit"], "record", None),
            (graph["audit"].entries[1], "previous_revision", None),
        )
        for obj, field, value in cases:
            with self.subTest(type=type(obj).__name__, field=field):
                with self.assertRaises(FrozenInstanceError):
                    setattr(obj, field, value)

    def test_pickle_preserves_cross_result_aliases_without_merging_equal_objects(self):
        graph = synthetic_graph()
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                restored = pickle.loads(pickle.dumps(graph, protocol=protocol))
                self.assert_graph_contract(restored, graph)
                self.assert_graph_frozen(restored)

    def test_deepcopy_preserves_cross_result_aliases_and_frozen_snapshots(self):
        graph = synthetic_graph()
        restored = copy.deepcopy(graph)
        self.assert_graph_contract(restored, graph)
        self.assert_graph_frozen(restored)
        restored.pop("record")
        self.assertIs(graph["record"], graph["repeated_record"])


class SerializationSubprocessTests(unittest.TestCase):
    def run_script(self, script, *arguments):
        environment = os.environ.copy()
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        result = subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(script), *arguments],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "serialization contract passed")

    def check_import_order(self, first, second):
        # Protocol 0 GLOBAL names have no binary length prefixes. These bytes are
        # generated locally, then use the pre-extraction module paths as old pickles did.
        payload = pickle.dumps(synthetic_graph(), protocol=0)
        legacy_payload = payload.replace(b"apps.revision_core.", b"apps.editorial_demo.")
        self.assertNotEqual(payload, legacy_payload)
        self.run_script(
            """\
            import base64
            import importlib
            import pickle
            import sys

            for root in sys.argv[1:3]:
                importlib.import_module(root + '.revision_history')
                importlib.import_module(root + '.revision_comparison')
            from apps.revision_core import revision_history as core_history
            from apps.revision_core import revision_comparison as core_comparison
            from apps.editorial_demo import revision_history as legacy_history
            from apps.editorial_demo import revision_comparison as legacy_comparison

            for encoded in sys.argv[3:]:
                graph = pickle.loads(base64.b64decode(encoded))
                record = graph['record']
                assert type(graph['history'][0]) is core_history.HistoryEntry
                assert type(graph['history'][0]) is legacy_history.HistoryEntry
                assert type(graph['comparison']) is core_comparison.RevisionComparison
                assert type(graph['comparison']) is legacy_comparison.RevisionComparison
                assert graph['history'][0].revision is record.history[0]
                assert graph['audit'].record is record
                assert graph['audit'].entries[1].previous_revision is record.history[0]
                assert legacy_history.select_revisions(graph['history'], '9', '2') == (
                    record.history[1], record.history[0])
                assert legacy_comparison.compare_revisions(*record.history) == graph['comparison']
                # Re-emitting a legacy-path instance must use the neutral definitions.
                rewritten = pickle.dumps(graph, protocol=0)
                assert b'apps.editorial_demo.' not in rewritten
                assert b'apps.revision_core.' in rewritten
            print('serialization contract passed')
            """,
            first,
            second,
            base64.b64encode(payload).decode("ascii"),
            base64.b64encode(legacy_payload).decode("ascii"),
        )

    def test_legacy_first_import_deserializes_old_and_neutral_graphs(self):
        self.check_import_order("apps.editorial_demo", "apps.revision_core")

    def test_core_first_import_deserializes_old_and_neutral_graphs(self):
        self.check_import_order("apps.revision_core", "apps.editorial_demo")

    def test_cold_deserialization_and_deepcopy_need_no_editorial_or_framework(self):
        payload = pickle.dumps(synthetic_graph(), protocol=pickle.HIGHEST_PROTOCOL)
        self.run_script(
            """\
            import base64
            import copy
            import importlib.abc
            import os
            import pickle
            import sys

            blocked = ('apps.editorial_demo', 'django', 'config', 'psycopg', 'psycopg2')

            class RejectDependency(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if any(fullname == root or fullname.startswith(root + '.') for root in blocked):
                        raise AssertionError('Forbidden dependency: ' + fullname)
                    return None

            assert 'DJANGO_SETTINGS_MODULE' not in os.environ
            assert not any(name == root or name.startswith(root + '.')
                           for name in sys.modules for root in blocked)
            sys.meta_path.insert(0, RejectDependency())
            graph = pickle.loads(base64.b64decode(sys.argv[1]))
            from apps.revision_core.revision_history import select_revisions
            from apps.revision_core.revision_comparison import compare_revisions

            for restored in (graph, copy.deepcopy(graph)):
                record = restored['record']
                assert restored['sibling'].intake is record.intake
                assert restored['audit'].record is record
                assert restored['audit'].entries[1].previous_revision is record.history[0]
                before, after = select_revisions(restored['history'], '2', '9')
                assert before is record.history[0] and after is record.history[1]
                assert restored['comparison'].before_references[0].reference is restored['reference']
                assert compare_revisions(before, after) == restored['comparison']
            assert not any(name == root or name.startswith(root + '.')
                           for name in sys.modules for root in blocked)
            print('serialization contract passed')
            """,
            base64.b64encode(payload).decode("ascii"),
        )
