"""Protect source fidelity and prevent credit from planned or wrong-head checks."""

import copy
import unittest
from unittest.mock import patch

import build


class ScopeTraceTests(unittest.TestCase):
    def execution_fixture(self, browser=False):
        sha = build.BASE_SHA
        refs = [
            {"path": "tests/synthetic/test_boundary.py", "symbol": "Boundary.test_allow"},
            {"path": "tests/synthetic/test_boundary.py", "symbol": "Boundary.test_deny"},
        ]
        group = {
            "product_sha": sha,
            "browser_test": "synthetic" if browser else None,
            "receipts": [],
        }
        sources = {}
        for major in (17, 18):
            name = f"synthetic-pg{major}"
            group["receipts"].append(
                {
                    "postgres_major": major,
                    "head_sha": sha,
                    "run_id": 1,
                    "job_id": major,
                    "status": "completed",
                    "conclusion": "success",
                    "excerpt": name,
                }
            )
            sources[name] = {
                "head_sha": sha,
                "run_id": 1,
                "job_id": major,
                "lines": [
                    "TESTED_SHA=" + sha,
                    "test_allow (tests.synthetic.test_boundary.Boundary.test_allow) ... ok",
                    "test_deny (tests.synthetic.test_boundary.Boundary.test_deny) ... ok",
                    "FATWA_BROWSER_SANDBOX: 1",
                ],
            }
        return group, refs, sources

    def test_all_556_original_rows_and_historical_evidence_remain_exact(self):
        import json

        old = build.baseline()
        generated = build.render()
        rows = json.loads(generated["matrix.json"])
        self.assertEqual(len(rows), 556)
        for previous, current in zip(old["matrix.json"], rows, strict=True):
            self.assertEqual({k: current[k] for k in previous}, previous)
        self.assertEqual(json.loads(generated["evidence.json"])["historical"], old["evidence.json"])
        self.assertEqual(json.loads(generated["summary.json"])["status_upgrades"], 0)
        self.assertEqual(rows[0]["v13"]["attested_original_excel_row"], 5)
        self.assertEqual(rows[-1]["v13"]["attested_original_excel_row"], 560)

    def test_changed_baseline_hash_cannot_be_used_as_same_source(self):
        original = build.read
        damaged = copy.deepcopy(original("baseline_manifest.json"))
        damaged["files"]["matrix.json"] = "0" * 64
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "baseline_manifest.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.baseline()

    def test_planned_test_or_missing_negative_cannot_credit_execution(self):
        assessment = copy.deepcopy(build.read("assessment.json"))
        group = assessment["groups"][0]
        group.update(
            state="VERIFIED_BOUNDED",
            product_sha=build.BASE_SHA,
            bounded_claim="fixture claim",
            code=["AGENTS.md"],
            positive_tests=["tests/synthetic/test_boundary.py#test_allow"],
        )
        with self.assertRaises(AssertionError):
            build.groups_for(assessment)

    def test_wrong_head_log_cannot_credit_either_major(self):
        group, refs, sources = self.execution_fixture()
        sources["synthetic-pg18"]["head_sha"] = "0" * 40
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_missing_negative_pass_on_one_major_is_rejected(self):
        group, refs, sources = self.execution_fixture()
        sources["synthetic-pg18"]["lines"] = [
            line for line in sources["synthetic-pg18"]["lines"] if not line.startswith("test_deny")
        ]
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_browser_without_protected_flag_is_not_credited(self):
        group, refs, sources = self.execution_fixture(browser=True)
        with patch.object(build, "read", side_effect=sources.__getitem__):
            build.check_execution(group, refs)
        sources["synthetic-pg17"]["lines"] = [
            line for line in sources["synthetic-pg17"]["lines"] if "SANDBOX" not in line
        ]
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_completion_or_percentage_cannot_be_inferred_from_evidence(self):
        for mutation in ("state", "percentage"):
            assessment = copy.deepcopy(build.read("assessment.json"))
            if mutation == "state":
                assessment["groups"][0]["state"] = "COMPLETE"
            else:
                assessment["percentage"] = 100
            with self.assertRaises(AssertionError):
                build.groups_for(assessment)

    def test_parent_reported_hash_is_not_local_original_verification(self):
        original = build.read
        damaged = copy.deepcopy(original("source_bytes.json"))
        damaged["local_original_byte_verification"] = True
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "source_bytes.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.render()

    def test_missing_or_ambiguous_code_symbol_cannot_be_cited(self):
        with self.assertRaises(AssertionError):
            build.reference("apps/casework/services.py#invented_v13_function", build.BASE_SHA)

    def test_parent_attestation_cannot_erase_date_serialization_differences(self):
        original = build.read
        damaged = copy.deepcopy(original("source_bytes.json"))
        damaged["independent_attestation"]["scope_comparison"][
            "whole_workbook_string_equivalence"
        ] = True
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "source_bytes.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.render()


if __name__ == "__main__":
    unittest.main()
