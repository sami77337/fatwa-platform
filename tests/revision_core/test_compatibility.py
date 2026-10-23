"""Legacy imports retain the same public objects and immutable result contracts."""

import importlib
import inspect
import pickle
import unittest
from dataclasses import FrozenInstanceError, asdict, replace

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.fatwa_drafts.domain import DraftRecord, Revision

_EXPORTS = {
    "revision_history": (
        "re", "dataclass", "DraftRecord", "Revision", "IntakeItem", "text",
        "compare_revisions", "HistoryDataError", "InvalidRevisionId", "UnknownRevisionId",
        "HistoryEntry", "build_history", "select_revisions",
    ),
    "revision_comparison": (
        "dataclass", "SequenceMatcher", "Literal", "Revision", "ReferenceLink",
        "MAX_TEXT_LENGTH", "ChangeKind", "TextPart", "TextComparison",
        "ReferenceComparison", "ChangeTarget", "RevisionComparison", "compare_revisions",
    ),
}
_DEFINITIONS = {
    "revision_history": (
        "HistoryDataError", "InvalidRevisionId", "UnknownRevisionId", "HistoryEntry",
        "build_history", "select_revisions",
    ),
    "revision_comparison": (
        "TextPart", "TextComparison", "ReferenceComparison", "ChangeTarget",
        "RevisionComparison", "compare_revisions",
    ),
}


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.history = importlib.import_module("apps.revision_core.revision_history")
        self.comparison = importlib.import_module("apps.revision_core.revision_comparison")
        self.legacy_history = importlib.import_module("apps.editorial_demo.revision_history")
        self.record = REVISION_HISTORY_RECORD

    def test_every_legacy_public_export_is_the_identical_core_object(self):
        for suffix, names in _EXPORTS.items():
            legacy = importlib.import_module("apps.editorial_demo." + suffix)
            core = importlib.import_module("apps.revision_core." + suffix)
            self.assertEqual({name for name in vars(legacy) if not name.startswith("_")},
                             set(names))
            for name in names:
                with self.subTest(module=suffix, export=name):
                    self.assertIs(getattr(legacy, name), getattr(core, name))

    def test_audit_uses_the_same_core_types_and_history_builder(self):
        from apps.fatwa_drafts import revision_audit

        self.assertIs(revision_audit.HistoryEntry, self.history.HistoryEntry)
        self.assertIs(revision_audit.HistoryDataError, self.history.HistoryDataError)
        self.assertIs(revision_audit.build_history, self.history.build_history)
        signature = inspect.signature(revision_audit.build_revision_audit)
        flag = signature.parameters["synthetic_fixtures_only"]
        self.assertIs(flag.default, False)
        self.assertEqual(flag.kind, inspect.Parameter.KEYWORD_ONLY)
        with self.assertRaises(self.legacy_history.HistoryDataError) as raised:
            revision_audit.build_revision_audit(self.record)
        self.assertIs(type(raised.exception), self.history.HistoryDataError)
        self.assertEqual(str(raised.exception), "audit: synthetic_fixture_acknowledgement_required")

    def test_public_entry_point_signatures_keep_parameters_annotations_and_defaults(self):
        parameter = inspect.Parameter
        positional = parameter.POSITIONAL_OR_KEYWORD
        cases = (
            (self.history.build_history, [("record", DraftRecord)],
             tuple[self.history.HistoryEntry, ...]),
            (self.history.select_revisions,
             [("entries", tuple[self.history.HistoryEntry, ...]),
              ("before", object), ("after", object)], tuple[Revision, Revision]),
            (self.comparison.compare_revisions, [("before", Revision), ("after", Revision)],
             self.comparison.RevisionComparison),
        )
        for function, parameters, returned in cases:
            with self.subTest(function=function.__name__):
                expected = inspect.Signature(
                    [parameter(name, positional, annotation=annotation)
                     for name, annotation in parameters], return_annotation=returned,
                )
                self.assertEqual(inspect.signature(function), expected)

    def test_legacy_pickle_global_paths_resolve_to_core_definitions(self):
        for suffix, names in _DEFINITIONS.items():
            core = importlib.import_module("apps.revision_core." + suffix)
            for name in names:
                with self.subTest(module=suffix, definition=name):
                    # Protocol 0 GLOBAL records use the original fully qualified path.
                    legacy_global = f"capps.editorial_demo.{suffix}\n{name}\n.".encode("ascii")
                    definition = getattr(core, name)
                    self.assertIs(pickle.loads(legacy_global), definition)
                    self.assertIs(pickle.loads(pickle.dumps(definition)), definition)
                    self.assertEqual(definition.__module__, "apps.revision_core." + suffix)

    def test_result_instances_roundtrip_with_identical_alias_types(self):
        entry = self.history.build_history(self.record)[1]
        comparison = self.comparison.compare_revisions(*self.record.history[:2])
        for result in (entry, comparison, self.history.HistoryDataError("invalid_history")):
            with self.subTest(result=type(result).__name__):
                restored = pickle.loads(pickle.dumps(result))
                self.assertIs(type(restored), type(result))
                if isinstance(result, Exception):
                    self.assertEqual(restored.args, result.args)
                else:
                    self.assertEqual(restored, result)

    def test_old_exception_catches_preserve_validation_order_messages_and_causes(self):
        first = self.record.history[0]
        cases = (
            ((), "invalid_history", None, None),
            ((replace(first, number=True, answer=None),),
             "invalid_or_duplicate_revision_identity", None, None),
            ((replace(first, action="", answer=None),), "invalid_history_content",
             ValueError, "history.action: required_or_control_character"),
            ((replace(first, answer="x" * 10001),), "invalid_history_content",
             ValueError, "comparison_text_invalid_or_too_long"),
        )
        for revisions, message, cause_type, cause_message in cases:
            with self.subTest(message=message, cause=cause_message):
                with self.assertRaises(self.legacy_history.HistoryDataError) as raised:
                    self.history.build_history(replace(self.record, history=revisions))
                self.assertIs(type(raised.exception), self.history.HistoryDataError)
                self.assertEqual(str(raised.exception), message)
                if cause_type is None:
                    self.assertIsNone(raised.exception.__cause__)
                else:
                    self.assertIsInstance(raised.exception.__cause__, cause_type)
                    self.assertEqual(str(raised.exception.__cause__), cause_message)
        entries = self.history.build_history(self.record)
        with self.assertRaises(self.legacy_history.InvalidRevisionId) as invalid:
            self.history.select_revisions(entries, "01", "3")
        self.assertIs(type(invalid.exception), self.history.InvalidRevisionId)
        self.assertEqual(str(invalid.exception), "invalid_or_missing_revision_identity")
        with self.assertRaises(self.legacy_history.UnknownRevisionId) as unknown:
            self.history.select_revisions(entries, "3", "1")
        self.assertIs(type(unknown.exception), self.history.UnknownRevisionId)
        self.assertEqual(str(unknown.exception), "unknown_revision_identity")
        self.assertIsInstance(unknown.exception.__cause__, KeyError)
        self.assertEqual(unknown.exception.__cause__.args, ("3",))

    def test_core_results_preserve_exact_text_sources_order_and_immutability(self):
        first = replace(self.record.history[0], title="أ", answer=" \t\r\n ")
        second = replace(first, number=7, title="ا\u0654", answer=" \t\n ",
                         reference_links=first.reference_links[::-1])
        record = replace(self.record, history=(second, first))
        original = asdict(record)
        history = self.history.build_history(record)
        self.assertEqual([entry.revision.number for entry in history], [1, 7])
        self.assertIs(history[0].revision, first)
        self.assertIs(history[1].revision, second)
        self.assertEqual(history[1].changed_fields,
                         ("العنوان", "نص المسودة — حقل التحرير البشري"))
        self.assertEqual(history[1].reference_positions_changed, 2)
        result = self.comparison.compare_revisions(first, second)
        for field in result.fields:
            self.assertEqual("".join(part.text for part in field.before), getattr(first, field.key))
            self.assertEqual("".join(part.text for part in field.after), getattr(second, field.key))
        self.assertIs(result.after_references[0].reference, second.reference_links[0])
        self.assertIs(result.after_references[1].reference, second.reference_links[1])
        self.assertEqual(result, self.comparison.compare_revisions(first, second))
        self.assertEqual(history, self.history.build_history(record))
        self.assertEqual(asdict(record), original)
        with self.assertRaises(FrozenInstanceError):
            history[0].previous_number = 3
        with self.assertRaises(FrozenInstanceError):
            result.references_changed = False
