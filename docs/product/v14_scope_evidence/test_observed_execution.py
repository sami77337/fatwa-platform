"""Negative and positive tests for the bounded observed-execution receipt.

These tests read pinned *repository* blobs, not live external services; they do
not rerun Django, Chrome or PostgreSQL, and they do not award owner acceptance.
"""

import copy
import json
import unittest
from pathlib import Path

try:
    from .verify_observed_execution import EvidenceError, check, git_reader
except ImportError:
    from verify_observed_execution import EvidenceError, check, git_reader

HERE = Path(__file__).resolve().parent


class ObservedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observations = json.loads(
            (HERE / "observed_execution.json").read_text(encoding="utf-8")
        )
        cls.candidates = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))

    def validate(self, mutate=None):
        receipt = copy.deepcopy(self.observations)
        if mutate is not None:
            mutate(receipt)
        return check(receipt, self.candidates, git_reader)

    def reject(self, mutate):
        with self.assertRaises((EvidenceError, KeyError, TypeError)):
            self.validate(mutate)

    def test_real_pinned_observations_are_consistent_not_accepted(self):
        result = self.validate()
        self.assertEqual(result["groups"], 4)
        self.assertEqual(result["owner_points_with_bounded_observations"], 11)
        self.assertEqual(result["postgreSQL_majors"], [17, 18])
        self.assertEqual(result["new_completed_points"], 0)
        self.assertEqual(result["acceptance"], "HOLD")

    def test_wrong_head_cannot_inherit_ci(self):
        self.reject(lambda d: d.update(product_sha="f" * 40))
        self.reject(lambda d: d["executions"][0].update(tested_sha="f" * 40))

    def test_missing_pg18_or_wrong_job_is_rejected(self):
        self.reject(lambda d: d["executions"].pop())
        self.reject(lambda d: d["executions"][1].update(job_id=134656248871))

    def test_original_owner_text_and_classification_cannot_change(self):
        self.reject(lambda d: d["groups"][0]["owner_points"][0].update(original_text="rewritten"))
        self.reject(lambda d: d["groups"][0]["owner_points"][0].update(preserved_status="COMPLETE"))

    def test_forged_positive_or_missing_negative_is_rejected(self):
        self.reject(lambda d: d["executions"][0]["observed_tests"][0].update(observed_line="... ok"))
        self.reject(lambda d: d["groups"][0].update(negative_tests=[]))
        self.reject(lambda d: d["executions"][0]["observed_tests"].pop())

    def test_file_integrity_is_pinned(self):
        self.reject(lambda d: d["groups"][0]["code"][0].update(blob_sha="0" * 40))
        self.reject(
            lambda d: d["groups"][0]["positive_tests"][0].update(
                path="apps/irrelevant/test_fabricated.py"
            )
        )

    def test_no_status_or_percentage_upgrade(self):
        self.reject(lambda d: d.update(status_upgrades=1))
        self.reject(lambda d: d.update(percentage=84))
        self.reject(lambda d: d.update(acceptance="PASSED"))

    def test_duplicate_groups_and_owner_points_are_denied(self):
        self.reject(lambda d: d["groups"][1].update(candidate_group="recording-controls"))
        self.reject(lambda d: d["groups"][1]["owner_points"][0].update(id=70))

    def test_pdf_plugin_limit_remains_explicit(self):
        self.reject(lambda d: d.update(limits=["All PDF pages verified", "All accepted", "Complete"]))


if __name__ == "__main__":
    unittest.main()
