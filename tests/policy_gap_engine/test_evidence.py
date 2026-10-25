"""Source integrity, synthetic ID membership and honest evidence counts."""

import importlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.permission_lab import sources


class GapEvidenceTests(unittest.TestCase):
    def service(self):
        try:
            return importlib.import_module("apps.policy_gap_engine.services")
        except ModuleNotFoundError:
            self.fail("The policy evidence report is absent")

    def test_synthetic_coverage_never_counts_as_historical_or_approval_coverage(self):
        evidence = self.service().inspect_evidence()
        self.assertEqual(evidence["status"], "SYNTHETIC_ONLY")
        self.assertEqual(evidence["provenance"]["source_commit"], sources.SOURCE_COMMIT)
        self.assertEqual(evidence["provenance"]["inventory_sha256"], sources.INVENTORY_SHA256)
        coverage = evidence["coverage"]
        self.assertEqual(
            coverage["synthetic"],
            {"actions": 4, "transitions": 1, "source_id_membership_verified": 5},
        )
        self.assertEqual(coverage["historical_actions"], {"expected": 70, "supplied": 0})
        self.assertEqual(coverage["historical_transitions"], {"expected": 58, "supplied": 0})
        self.assertEqual(coverage["U03"], {"expected": 48, "supplied": 0, "approved": 0})
        self.assertEqual(coverage["U10"], {"expected": 28, "supplied": 0, "approved": 0})
        self.assertFalse(evidence["policy_approval_verified"])
        self.assertFalse(evidence["source_acceptance_passed"])
        self.assertEqual(len(evidence["records"]), 5)
        for row in evidence["records"]:
            self.assertEqual(row["binding_scope"], "SYNTHETIC_ID_MEMBERSHIP_ONLY")
            self.assertEqual(row["policy_status"], "POLICY_PENDING")

    def test_each_pinned_source_failure_removes_all_verified_coverage(self):
        service = self.service()
        original = Path(sources.__file__).parent / "upstream"
        for name in (
            "validator.py",
            "inventory.schema.json",
            "synthetic_inventory.json",
            "synthetic_review_excerpt.json",
            "__init__.py",
        ):
            for mode in ("missing", "tampered"):
                with self.subTest(name=name, mode=mode), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder) / "upstream"
                    shutil.copytree(original, root)
                    file = root / name
                    if mode == "missing":
                        file.unlink()
                    else:
                        file.write_bytes(file.read_bytes() + b" ")
                    with patch.object(sources, "_UPSTREAM_ROOT", root):
                        report = service.build_report()
                    self.assertEqual(report["status"], "EVIDENCE_UNAVAILABLE")
                    self.assertEqual(report["evidence"]["records"], [])
                    self.assertIsNone(report["evidence"]["coverage"]["synthetic"])
                    self.assertEqual(report["adversarial_checks"]["status"], "NOT_RUN")
                    self.assertEqual(report["effect"], "DENY")
                    self.assertNotIn(folder, service.canonical_json(report))

    def test_evidence_reports_are_fresh_and_gates_never_advance(self):
        service = self.service()
        first = service.inspect_evidence()
        first["coverage"]["historical_actions"]["supplied"] = 70
        report = service.build_report()
        self.assertEqual(report["evidence"]["coverage"]["historical_actions"]["supplied"], 0)
        self.assertEqual(
            report["gates"],
            {
                "gate_b": "NOT_PASSED",
                "gates_c_d_e": "HOLD",
                "phase01": "BLOCKED",
                "scope": "SCOPE_DEVIATION_HOLD",
                "deployment": "NOT_DEPLOYED",
            },
        )
        self.assertEqual(report["active_grants"], 0)

    def test_synthetic_source_membership_and_policy_token_are_checked(self):
        service = self.service()
        for field, value in (
            ("source_ref", {"document_id": "synthetic-review", "record_id": "absent-record"}),
            (
                "source_ref",
                {"document_id": "invented-source", "record_id": "synthetic::answer.create"},
            ),
            ("policy_token", "ASSUMED_APPROVAL"),
        ):
            inventory = sources.load_inventory()
            inventory["actions"][2][field] = value
            with self.subTest(field=field, value=value):
                with patch.object(sources, "load_inventory", return_value=inventory):
                    evidence = service.inspect_evidence()
                self.assertEqual(evidence["status"], "UNAVAILABLE")
                self.assertEqual(evidence["records"], [])

    def test_failure_after_initial_validation_discards_partial_report(self):
        service = self.service()
        from apps.policy_gap_engine.evidence import load_evidence

        initial = load_evidence()
        with patch.object(
            service,
            "load_evidence",
            side_effect=[initial, sources.SourceUnavailable("late failure")],
        ):
            report = service.build_report()
        self.assertEqual(report["status"], "EVIDENCE_UNAVAILABLE")
        self.assertEqual(report["requests"], [])
        self.assertIsNone(report["evidence"]["coverage"]["synthetic"])


if __name__ == "__main__":
    unittest.main()
