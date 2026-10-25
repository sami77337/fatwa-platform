"""Cross-component evidence, including adversarial identity and replay checks."""

import builtins
import io
import json
import os
import socket
from dataclasses import replace
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch


class JourneyTests(TestCase):
    def run_journey(self):
        from apps.fast6_journey.services import run_journey

        return run_journey(synthetic_fixtures_only=True)

    def test_real_components_are_deterministic_and_report_disconnected_boundaries(self):
        report = self.run_journey()
        self.assertEqual(report.json_bytes, self.run_journey().json_bytes)
        self.assertEqual(report.sha256, sha256(report.json_bytes).hexdigest())
        data = report.payload()
        self.assertEqual(data["result"], "PASS_WITH_GAPS")
        self.assertEqual(len(data["cases"]), 20)
        self.assertEqual(data["transcript"]["draft_count"], 0)
        self.assertEqual(
            data["transcript"]["prepared_input_sha256"],
            data["transcript"]["prepared_output_sha256"],
        )
        self.assertEqual(
            {edge["id"] for edge in data["connections"] if edge["status"] == "NOT_CONNECTED"},
            {
                "transcript_to_stock_queue",
                "prepared_to_rehearsal",
                "rehearsal_to_export",
                "permission_to_case",
            },
        )
        self.assertEqual(data["execution"]["browser"], "NOT_RUN")
        self.assertEqual(data["execution"]["postgres"], "NOT_RUN")
        self.assertEqual(
            data["holds"],
            [
                "Gate B NOT_PASSED",
                "C/D/E HOLD",
                "Phase01 BLOCKED",
                "SCOPE_DEVIATION_HOLD",
                "NOT_DEPLOYED",
            ],
        )
        data["cases"].clear()
        self.assertEqual(len(report.payload()["cases"]), 20)

    def test_exact_sources_revisions_rejections_and_closed_catalog_links(self):
        data = self.run_journey().payload()
        cases = {row["identity"]["case_key"]: row for row in data["cases"]}
        self.assertEqual(cases["history"]["revision_numbers"], [1, 2, 4, 7, 9, 11])
        self.assertEqual(
            cases["intake-1"]["identity"]["external_id"],
            cases["intake-4"]["identity"]["external_id"],
        )
        self.assertNotEqual(cases["intake-1"]["identity"], cases["intake-4"]["identity"])
        ready = cases["intake-7"]
        self.assertEqual(ready["references"][0]["catalog_url"], "/fiqh/nodes/2?edition=7001")
        self.assertIsNone(ready["references"][0]["empty_catalog_url"])
        prepared = cases["batch-synthetic-csv-1"]
        self.assertIn("\r\n", prepared["question"])
        self.assertIn("e\u0301", prepared["question"])
        self.assertIsNone(prepared["references"][0]["catalog_url"])
        self.assertEqual(prepared["references"][0]["status"], "unverified")
        self.assertEqual(data["diagnostics"]["malformed_batches"], ["synthetic-malformed"])
        self.assertTrue(data["diagnostics"]["duplicate_groups"])
        self.assertTrue(
            all(
                not item["allowed"] and item["effect"] == "DENY"
                for item in data["authorization"]["decisions"]
            )
        )
        self.assertTrue(all(case["scholarly_decision"] is None for case in data["cases"]))

    def test_guard_runs_before_fixture_reads_and_rejects_production(self):
        from apps.fast6_journey import services

        with patch.object(services, "build_queue_catalog") as loader:
            for flag in (False, None, 1, "true"):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    services.run_journey(synthetic_fixtures_only=flag)
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                with self.assertRaises(ValueError):
                    self.run_journey()
            loader.assert_not_called()

    def test_mismatched_case_with_same_key_and_external_id_cannot_join(self):
        from apps.fast6_journey import services

        investigation = services.build_investigation()
        first = investigation.cases[0]
        corrupt = replace(first, case=replace(first.case, payload_sha256="0" * 64))
        changed = replace(investigation, cases=(corrupt, *investigation.cases[1:]))
        with patch.object(services, "build_investigation", return_value=changed):
            with self.assertRaisesRegex(services.JourneyError, "identity"):
                self.run_journey()

    def test_duplicate_case_keys_and_export_packet_tampering_fail(self):
        from apps.editorial_export.services import ExportBundle
        from apps.fast6_journey import services

        catalog = services.build_queue_catalog()
        with patch.object(
            services,
            "build_queue_catalog",
            return_value=replace(catalog, rows=(*catalog.rows, catalog.rows[0])),
        ):
            with self.assertRaisesRegex(services.JourneyError, "identity"):
                self.run_journey()
        bundle = services.build_export(synthetic_fixtures_only=True)
        files = dict(bundle.files)
        files["cases.csv"] += b"\r\n"
        with patch.object(
            services, "build_export", return_value=ExportBundle(tuple(files.items()))
        ):
            with self.assertRaises(ValueError):
                self.run_journey()

    def test_reference_occurrences_cannot_move_between_cases_with_correct_case_identity(self):
        from apps.fast6_journey import services

        investigation = services.build_investigation()
        donor = next(row for row in investigation.cases if row.case.key == "intake-7")
        for key in ("history", "intake-1"):
            rows = tuple(
                replace(row, references=donor.references) if row.case.key == key else row
                for row in investigation.cases
            )
            with (
                self.subTest(key=key),
                patch.object(
                    services, "build_investigation", return_value=replace(investigation, cases=rows)
                ),
                self.assertRaisesRegex(services.JourneyError, "reference_occurrence"),
            ):
                self.run_journey()

    def test_reference_evidence_source_offsets_and_hash_must_match_original_occurrence(self):
        from apps.fast6_journey import services

        investigation = services.build_investigation()
        selected = next(row for row in investigation.cases if row.case.key == "intake-7")
        for change in (
            {"ordinal": 2},
            {"source_sha256": "0" * 64},
            {"source_start": None},
            {"source_text": "another source"},
            {"original_identity": '{"source_id":"unrelated"}'},
            {"verified_identity": "{}"},
            {"evidence": "null"},
            {"contract_status": "UNVERIFIED"},
        ):
            ref = replace(selected.references[0], **change)
            rows = tuple(
                replace(row, references=(ref,)) if row is selected else row
                for row in investigation.cases
            )
            with (
                self.subTest(change=change),
                patch.object(
                    services, "build_investigation", return_value=replace(investigation, cases=rows)
                ),
                self.assertRaisesRegex(services.JourneyError, "reference_occurrence"),
            ):
                self.run_journey()

    def test_replay_rejects_changed_report_even_with_recomputed_hash(self):
        from apps.fast6_journey.services import JourneyError, verify_journey

        report = self.run_journey()
        verify_journey(report.json_bytes, synthetic_fixtures_only=True)
        modified = report.payload()
        modified["connections"][0]["status"] = "CONNECTED"
        changed = json.dumps(modified, ensure_ascii=False).encode()
        with self.assertRaises(JourneyError):
            verify_journey(changed, synthetic_fixtures_only=True)
        for bad in (None, "{}", b"x" * 2_000_001):
            with self.subTest(kind=type(bad)), self.assertRaises(JourneyError):
                verify_journey(bad, synthetic_fixtures_only=True)

    def test_execution_uses_no_writes_sockets_database_or_processes(self):
        import subprocess

        from apps.reference_links.django_adapter import DjangoCatalog

        original_open = io.open
        original_builtin = builtins.open

        def guarded(opener):
            def call(file, mode="r", *args, **kwargs):
                if any(flag in mode for flag in "wax+"):
                    raise AssertionError("journey attempted file write")
                return opener(file, mode, *args, **kwargs)

            return call

        with (
            patch("io.open", guarded(original_open)),
            patch("builtins.open", guarded(original_builtin)),
            patch.object(socket, "socket", side_effect=AssertionError("network")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("process")),
            patch.object(DjangoCatalog, "lookup", side_effect=AssertionError("database")),
        ):
            self.assertEqual(self.run_journey().payload()["result"], "PASS_WITH_GAPS")
