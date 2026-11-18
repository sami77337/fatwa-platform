"""Negative checks protect source IDs, truthful evidence and reproducible output."""

import copy
import unittest
from unittest.mock import patch

import build
import validate


class EvidenceTests(unittest.TestCase):
    def test_package_source_and_output_integrity(self):
        validate.validate()

    def test_missing_or_duplicate_owner_id_cannot_silently_render(self):
        original = build.read
        source = original("sources/scope_read_1.json")
        damaged = copy.deepcopy(source)
        text = damaged["results"][0]["content"][3]
        self.assertIn("3,1,", text)
        damaged["results"][0]["content"][3] = text.replace("3,1,", "3,2,", 1)
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "sources/scope_read_1.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.sources()

    def test_missing_continuation_cannot_look_like_full_source(self):
        original = build.read
        damaged = copy.deepcopy(original("sources/scope_read_2.json"))
        damaged["results"][0]["has_more"] = True
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "sources/scope_read_2.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.sources()

    def test_nonexistent_test_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            build.reference("tests/casework/test_core.py#test_invented_pass")

    def test_repeated_decisions_are_preserved_without_inventing_original_ids(self):
        items = build.decisions()
        self.assertEqual(len({r["original_id"] for r in items}), 72)
        self.assertEqual(len(items), 77)
        for ident in ("D-023", "D-024", "D-044", "D-064", "D-069"):
            occurrences = [r["occurrence"] for r in items if r["original_id"] == ident]
            self.assertEqual(occurrences, [1, 2])
        self.assertTrue(any(r["original_id"] == "D-061" for r in items))

    def test_unreturned_ci_run_cannot_be_attached_as_execution(self):
        original = build.read
        damaged = copy.deepcopy(original("assessments.json"))
        damaged["evidence_groups"][0]["workflow_run_id"] = 1
        with patch.object(
            build, "read", side_effect=lambda n: damaged if n == "assessments.json" else original(n)
        ):
            with self.assertRaises(AssertionError):
                build.build()


if __name__ == "__main__":
    unittest.main()
