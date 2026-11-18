"""Protect source fidelity and prevent credit from planned or wrong-head checks."""

import copy
import json
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
                    f"SYNTHETIC_POSTGRES=postgres (PostgreSQL) {major}.0; test fixture only",
                    "test_allow (tests.synthetic.test_boundary.Boundary.test_allow) ... ok",
                    "test_deny (tests.synthetic.test_boundary.Boundary.test_deny) ... ok",
                    "FATWA_BROWSER_SANDBOX: 1",
                    "V13_BROWSER_PROOF="
                    + json.dumps(
                        {
                            "tested_sha": sha,
                            "sandbox": True,
                            "external_requests": 0,
                            "page_errors": 0,
                            "canonical": {"cases": 1},
                            "widths": [320, 1280],
                            "recovery": {
                                "state": "READY",
                                "target_http": "PASS",
                                "encrypted_only": True,
                                "independent_target_postgres_server": True,
                                "separate_key": True,
                                "source_left_frozen": True,
                                "source_unchanged": True,
                                "partial_delivery_preserved": True,
                                "wrong_key_and_hash_before_target": "DENIED",
                            },
                        }
                    ),
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
            negative_tests=[],
            credited_owner_points=[25],
            browser_test="tests/synthetic/test_boundary.py#test_browser",
        )
        with self.assertRaises(AssertionError):
            build.groups_for(assessment)

    def test_wrong_head_log_cannot_credit_either_major(self):
        group, refs, sources = self.execution_fixture()
        sources["synthetic-pg18"]["head_sha"] = "0" * 40
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_successful_ci_on_known_blocked_head_cannot_credit_affected_scope(self):
        assessment = copy.deepcopy(build.read("assessment.json"))
        blocked = build.read("execution_history.json")["entries"][0]
        group = next(g for g in assessment["groups"] if g["id"] == "timed-citations")
        group.update(state="VERIFIED_BOUNDED", product_sha=blocked["sha"])
        with self.assertRaisesRegex(AssertionError, "known security blocker"):
            build.groups_for(assessment)

    def test_cd22_green_recovery_receipt_cannot_override_sec13_01(self):
        assessment = copy.deepcopy(build.read("assessment.json"))
        history = build.read("suspended_recovery_evidence.json")["historical_assessment"]
        assessment["groups"] = [
            history if g["id"] == "connected-recovery" else g for g in assessment["groups"]
        ]
        with self.assertRaisesRegex(AssertionError, "known security blocker"):
            build.groups_for(assessment)

    def test_repaired_credit_keeps_old_suspension_and_unrelated_receipts(self):
        rows = json.loads(build.render()["matrix.json"])
        self.assertEqual(rows[424]["v13"]["verified_group_ids"], ["connected-recovery"])
        self.assertEqual(
            rows[424]["v13"]["evidence_shas"], ["feb4e521f3c2847403a0e0626ff34da6df7612cc"]
        )
        self.assertIn("browser-audio", rows[24]["v13"]["verified_group_ids"])
        self.assertEqual(
            rows[24]["v13"]["evidence_shas"], ["cd22cbd265db4b57124a1f091a041fd5200637b8"]
        )
        history = build.read("suspended_recovery_evidence.json")["historical_assessment"]
        self.assertEqual(len(history["receipts"]), 2)
        for receipt in history["receipts"]:
            self.assertEqual(build.read(receipt["excerpt"])["conclusion"], "success")

    def test_recovery_credit_requires_exact_independent_repair_review(self):
        group = next(
            g for g in build.read("assessment.json")["groups"] if g["id"] == "connected-recovery"
        )
        group["product_sha"] = "0" * 40
        with self.assertRaisesRegex(AssertionError, "repair review must name exact product"):
            build.check_repair_review(group)

    def test_repair_report_cannot_be_changed_or_promote_local_microphone(self):
        original = build.read
        group = next(
            g for g in original("assessment.json")["groups"] if g["id"] == "connected-recovery"
        )
        for key, value in (("report_sha256", "0" * 64), ("independent_browser", "PASS")):
            damaged = copy.deepcopy(original("recovery_repair_review.json"))
            damaged[key] = value
            with patch.object(
                build,
                "read",
                side_effect=lambda n: (
                    damaged if n == "recovery_repair_review.json" else original(n)
                ),
            ):
                with self.assertRaises(AssertionError):
                    build.check_repair_review(group)

    def test_missing_negative_pass_on_one_major_is_rejected(self):
        group, refs, sources = self.execution_fixture()
        sources["synthetic-pg18"]["lines"] = [
            line for line in sources["synthetic-pg18"]["lines"] if not line.startswith("test_deny")
        ]
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_mislabeled_major_cannot_credit_pg17_log_as_pg18(self):
        group, refs, sources = self.execution_fixture()
        sources["synthetic-pg18"]["lines"] = [
            line.replace("PostgreSQL) 18.", "PostgreSQL) 17.")
            for line in sources["synthetic-pg18"]["lines"]
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

    def test_declared_sandbox_does_not_override_observed_unprotected_browser(self):
        group, refs, sources = self.execution_fixture(browser=True)
        sources["synthetic-pg17"]["lines"][-1] = sources["synthetic-pg17"]["lines"][-1].replace(
            '"sandbox": true', '"sandbox": false'
        )
        with patch.object(build, "read", side_effect=sources.__getitem__):
            with self.assertRaises(AssertionError):
                build.check_execution(group, refs)

    def test_restore_claim_requires_actual_independent_ready_target_http_proof(self):
        group, refs, sources = self.execution_fixture(browser=True)
        group["id"] = "connected-recovery"
        with patch.object(build, "read", side_effect=sources.__getitem__):
            build.check_execution(group, refs)
        sources["synthetic-pg18"]["lines"][-1] = sources["synthetic-pg18"]["lines"][-1].replace(
            '"target_http": "PASS"', '"target_http": "NOT_RUN"'
        )
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
        damaged["local_reference_workbook_byte_verification"] = True
        with patch.object(
            build,
            "read",
            side_effect=lambda n: damaged if n == "source_bytes.json" else original(n),
        ):
            with self.assertRaises(AssertionError):
                build.render()

    def test_workbook_matching_does_not_establish_authoring_provenance(self):
        original = build.read
        for key, value in (
            ("byte_validation", "VERIFIED"),
            ("byte_identity_proved_by_workbook_match", True),
        ):
            damaged = copy.deepcopy(original("source_bytes.json"))
            damaged["authoring_document"][key] = value
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
