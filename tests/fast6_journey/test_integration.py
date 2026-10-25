"""Exact synthetic bridges; stock packets and permission boundaries stay intact."""

import copy
import json
import os
from dataclasses import replace
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.services import build_export
from apps.editorial_queue.services import build_queue_catalog
from tests.fast6_journey import test_cli, test_services


class IntegratedCliTests(TestCase):
    invoke = test_cli.JourneyCliTests.invoke

    def test_integrated_stdout_replays_and_keeps_real_blockers(self):
        result = self.invoke("--synthetic-fixtures-only", "--integrated")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        data = json.loads(result.stdout)
        self.assertEqual(data["schema"], "fatwa.fast6-integration.v1")
        self.assertEqual(
            result.stdout, self.invoke("--synthetic-fixtures-only", "--integrated").stdout
        )
        self.assertEqual(data["source_readiness"]["status"], "BLOCKED")
        self.assertEqual(data["source_readiness"]["owner_acceptance"], "NOT_RUN")

    def test_integrated_mode_cannot_bypass_production_guard(self):
        result = self.invoke("--synthetic-fixtures-only", "--integrated", production="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)


class IntegratedBridgeTests(TestCase):
    def run_report(self):
        from apps.fast6_journey.integration import run_integration

        return run_integration(synthetic_fixtures_only=True)

    run_journey = run_report
    test_execution_uses_no_writes_sockets_database_or_processes = (
        test_services.JourneyTests.test_execution_uses_no_writes_sockets_database_or_processes
    )

    def test_prepared_rehearsal_is_exported_against_exact_original_packet(self):
        before = build_export(synthetic_fixtures_only=True)
        report = self.run_report()
        data = report.payload()
        self.assertEqual(report.json_bytes, self.run_report().json_bytes)
        self.assertEqual(data["result"], "PASS_WITH_GAPS")
        self.assertEqual(
            {edge["id"] for edge in data["connections"] if edge["status"] == "NOT_CONNECTED"},
            {"transcript_to_stock_queue", "permission_to_case"},
        )
        self.assertEqual(len(data["projections"]), 20)
        original = {row["packet"]["identity"]["case_key"]: row for row in before.report()["cases"]}
        cases = {row.case.key: row.case for row in build_queue_catalog().rows}
        for item in data["projections"]:
            key = item["identity"]["case_key"]
            self.assertEqual(item["packet"], original[key]["packet"])
            self.assertEqual(item["packet_sha256"], original[key]["packet_sha256"])
            self.assertEqual(item["identity"]["input_sha256"], cases[key].payload_sha256)
            self.assertEqual(
                item["identity"]["source_sha256"],
                sha256(cases[key].raw_source.encode()).hexdigest(),
            )
            self.assertFalse(item["persisted"])
            self.assertFalse(item["scholarly_approval"])
            self.assertIsNone(item["packet"]["scholarly_decision"])
            if cases[key].record is None:
                self.assertIsNone(item["projection"]["record"])
                self.assertTrue(all(not step["accepted"] for step in item["steps"]))
            self.assertTrue(
                all(not step["accepted"] for step in item["steps"] if step["action"] == "published")
            )
        csv = next(
            row
            for row in data["projections"]
            if row["identity"]["case_key"] == "batch-synthetic-csv-1"
        )
        self.assertEqual(
            csv["packet"]["intake"]["question"], "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "
        )
        self.assertEqual(csv["projection"]["record"]["history"][-1]["state"], "draft_preparation")
        self.assertEqual(csv["projection"]["review"], "REVIEWED_INTERNAL")
        self.assertEqual(csv["identity"]["batch_id"], "synthetic-csv")
        self.assertEqual(csv["identity"]["row_ordinal"], 1)
        self.assertEqual(before.files, build_export(synthetic_fixtures_only=True).files)
        self.assertEqual(data["permission_gaps"]["effect"], "DENY")
        self.assertFalse(data["permission_gaps"]["allowed"])
        self.assertTrue(data["workflow_invariants"]["invariants_passed"])

    def test_guard_rejects_before_any_fixture_read(self):
        from apps.fast6_journey.integration import run_integration

        for flag in (False, None, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                run_integration(synthetic_fixtures_only=flag)
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}), self.assertRaises(ValueError):
            self.run_report()

    def test_same_key_cannot_join_tampered_source_or_record(self):
        from apps.fast6_journey import integration
        from apps.workflow_rehearsal.services import build_prepared_rehearsal

        real = build_prepared_rehearsal("batch-synthetic-csv-1", synthetic_fixtures_only=True)
        for altered in (
            replace(real, case=replace(real.case, payload_sha256="0" * 64)),
            replace(real, source_record=None),
            replace(real, case=replace(real.case, row_ordinal=2)),
        ):
            with patch.object(integration, "build_prepared_rehearsal", return_value=altered):
                with self.assertRaisesRegex(ValueError, "identity|source_record"):
                    self.run_report()

    def test_prepared_selector_rejects_aliases_and_absent_rows(self):
        from apps.workflow_rehearsal.services import build_prepared_rehearsal

        for key in ("batch-synthetic-csv-01", "batch-synthetic-csv-5", "history", None, []):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_prepared_rehearsal(key, synthetic_fixtures_only=True)

    def test_second_export_cannot_substitute_packet_with_same_claimed_hash(self):
        from apps.editorial_export.services import ExportBundle, encode_json
        from apps.fast6_journey import integration

        bundle = build_export(synthetic_fixtures_only=True)
        changed = bundle.report()
        changed["cases"][0]["packet"]["scholarly_decision"] = "forged"
        files = dict(bundle.files)
        files["report.json"] = encode_json(changed)
        with patch.object(
            integration, "build_export", return_value=ExportBundle(tuple(files.items()))
        ):
            with self.assertRaises(ValueError):
                self.run_report()

    def test_failed_permission_probe_prevents_aggregate_success(self):
        from apps.fast6_journey import integration

        baseline = integration.build_report()
        reports = [copy.deepcopy(baseline) for _ in range(4)]
        reports[0]["adversarial_checks"].update(status="FAIL", failed=1)
        reports[1]["requests"][0].update(allowed=True, effect="ALLOW")
        reports[2]["adversarial_checks"]["checks"][0]["passed"] = False
        reports[3]["adversarial_checks"].update(evaluated=0, checks=[])
        for report in reports:
            with self.subTest(report=reports.index(report)):
                with patch.object(integration, "build_report", return_value=report):
                    with self.assertRaisesRegex(ValueError, "permission"):
                        self.run_report()

    def test_invalid_owner_metadata_prevents_aggregate_success(self):
        from apps.fast6_journey import integration

        with patch.object(integration, "pinned_owner_manifest", return_value=b"{}"):
            with self.assertRaisesRegex(ValueError, "readiness"):
                self.run_report()

    def test_integrated_replay_refuses_tampering_and_bounded_wrong_types(self):
        from apps.fast6_journey.integration import verify_integration

        report = self.run_report()
        verify_integration(report.json_bytes, synthetic_fixtures_only=True)
        for raw in (report.json_bytes + b" ", b"x" * 2_000_001, None, "{}"):
            with self.subTest(kind=type(raw)), self.assertRaises(ValueError):
                verify_integration(raw, synthetic_fixtures_only=True)
