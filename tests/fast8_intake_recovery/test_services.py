"""Real fixed batches plus explicitly fabricated adversarial parser evidence."""

import base64
import hashlib
import socket
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.editorial_workbench.batch_fixtures import synthetic_inputs
from apps.fast8_intake_recovery.services import BATCH_IDS, _project, preview_recovery
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline.batches import PreparedInput
from apps.prepared_pipeline.diagnostics import diagnose_batches

PINS = (
    "0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8",
    "d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec",
    "e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363",
    "d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086",
)


class RecoveryTests(unittest.TestCase):
    def test_existing_fixture_identity_counts_and_unchanged_diagnostics(self):
        inputs = synthetic_inputs()
        self.assertEqual(tuple(entry.batch_id for entry in inputs), BATCH_IDS)
        self.assertEqual(tuple(hashlib.sha256(entry.raw).hexdigest() for entry in inputs), PINS)
        before = tuple(entry.raw for entry in inputs)
        upstream = diagnose_batches(inputs, synthetic_fixtures_only=True).report
        report = preview_recovery().report
        self.assertEqual(report["inputs"], upstream["inputs"])
        self.assertEqual(report["summary"]["selected_rows"], 11)
        self.assertEqual(report["summary"]["selected_failed_rows"], 6)
        self.assertEqual(report["summary"]["selected_failed_batches"], 1)
        for actual, expected in zip(report["rows"], upstream["rows"], strict=True):
            for field in ("batch_id", "row", "row_id", "provenance"):
                self.assertEqual(actual[field], expected[field])
            self.assertEqual(actual["recommendations"], expected["diagnostics"])
            for field in ("original", "findings"):
                self.assertEqual(actual[field], expected["preparation"][field])
            self.assertEqual(actual["upstream_statuses"], expected["preparation"]["statuses"])
            self.assertEqual(
                actual["csv_extra_cells"], expected["preparation"].get("csv_extra_cells", [])
            )
            self.assertNotIn("draft", actual)
        self.assertEqual(tuple(entry.raw for entry in inputs), before)

    def test_exact_bytes_offsets_crlf_unicode_and_source_ids(self):
        report = preview_recovery().report
        inputs = {entry.batch_id: entry.raw for entry in synthetic_inputs()}
        for entry in report["inputs"]:
            self.assertEqual(base64.b64decode(entry["raw_base64"]), inputs[entry["batch_id"]])
        for row in report["rows"]:
            provenance = row["provenance"]
            raw = inputs[row["batch_id"]]
            self.assertEqual(provenance["input_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(
                base64.b64decode(provenance["raw_base64"]),
                raw[provenance["byte_start"] : provenance["byte_end"]],
            )
        self.assertEqual(
            report["rows"][0]["original"]["question"], "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "
        )
        self.assertEqual(
            report["rows"][-1]["original"]["reference_links"][0]["source_id"], " W7-SOURCE"
        )
        self.assertEqual(report["rows"][3]["csv_extra_cells"], ["overflow-synthetic"])
        self.assertIsNone(report["rows"][7]["original"])

    def test_selecting_duplicate_keeps_cross_batch_block_and_all_locations(self):
        result = preview_recovery(batch_id="synthetic-csv", row=2)
        report = result.report
        self.assertTrue(result.has_failures)
        self.assertEqual(
            [(r["batch_id"], r["row"]) for r in report["rows"]], [("synthetic-csv", 2)]
        )
        self.assertEqual(report["rows"][0]["state"], "BLOCKED_INVALID")
        self.assertEqual(report["summary"]["collection_rows"], 11)
        self.assertEqual(len(report["collection_inputs"]), 4)
        self.assertEqual(len(report["duplicate_groups"]), 1)
        self.assertEqual(
            [(x["batch_id"], x["row"]) for x in report["duplicate_groups"][0]["locations"]],
            [("synthetic-csv", 2), ("synthetic-json", 1)],
        )
        self.assertIn("synthetic-json", result.preview_ar())

    def test_failed_filter_retains_original_ordinals_and_malformed_batch(self):
        report = preview_recovery(failed_only=True).report
        self.assertEqual(
            [(r["batch_id"], r["row"]) for r in report["rows"]],
            [
                ("synthetic-csv", 2),
                ("synthetic-csv", 4),
                ("synthetic-json", 1),
                ("synthetic-json", 3),
                ("synthetic-json", 4),
                ("synthetic-jsonl", 3),
            ],
        )
        self.assertEqual(report["summary"]["selected_failed_batches"], 1)
        selected = preview_recovery(batch_id="synthetic-jsonl", failed_only=True).report
        self.assertEqual([r["row"] for r in selected["rows"]], [3])
        self.assertEqual(selected["summary"]["selected_failed_batches"], 0)

    def test_malformed_batch_keeps_digest_code_and_no_invented_rows(self):
        result = preview_recovery(batch_id="synthetic-malformed")
        report = result.report
        self.assertEqual(report["rows"], [])
        self.assertTrue(result.has_failures)
        self.assertEqual(report["batch_failures"][0]["error_code"], "MALFORMED_INPUT")
        self.assertEqual(report["batch_failures"][0]["input_sha256"], PINS[-1])
        self.assertIsNone(report["batch_failures"][0]["row"])
        self.assertEqual(base64.b64decode(report["inputs"][0]["raw_base64"]), b'{"synthetic":')
        with self.assertRaisesRegex(ValidationError, "row_not_available"):
            preview_recovery(batch_id="synthetic-malformed", row=1)

    def test_nonblocked_is_review_only_never_accepted_or_source_verified(self):
        result = preview_recovery(batch_id="synthetic-jsonl", row=1)
        report = result.report
        self.assertFalse(result.has_failures)
        self.assertEqual(
            report["rows"][0]["upstream_statuses"], ["ready-for-editor", "references-unverified"]
        )
        self.assertEqual(report["rows"][0]["state"], "MANUAL_REVIEW_REQUIRED")
        self.assertEqual(report["accepted_record_count"], 0)
        self.assertTrue(report["preview_only"])
        self.assertFalse(report["resubmission_performed"])
        self.assertFalse(report["source_modification_performed"])
        self.assertEqual(report["source_inventory"], "NOT_SUPPLIED")
        self.assertEqual(report["reference_mapping"], "NOT_CONNECTED")
        self.assertEqual(
            report["gates"], {"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"}
        )
        self.assertEqual(report["phase01"], "BLOCKED")
        self.assertEqual(report["deployment"], "NOT_DEPLOYED")
        self.assertEqual(
            report["policy_acceptance"],
            {"U03": "OWNER_APPROVAL_PENDING", "U10": "OWNER_APPROVAL_PENDING"},
        )

    def test_exact_selectors_reject_paths_urls_and_coercion_before_diagnostics(self):
        with patch("apps.fast8_intake_recovery.services.diagnose_batches") as diagnose:
            for identity in (
                "../synthetic-csv",
                "C:\\private\\input.csv",
                "/tmp/input.json",
                "https://example.invalid/data",
                " synthetic-csv",
                "synthetic-csv ",
                "SYNTHETIC-CSV",
                "synthetic-csv\x00",
                "synthetic-csv:stream",
                "",
                b"synthetic-csv",
                [],
                1,
                True,
            ):
                with (
                    self.subTest(identity=identity),
                    self.assertRaisesRegex(ValidationError, "unknown_batch"),
                ):
                    preview_recovery(batch_id=identity)
            for row in (True, False, 0, -1, 1001, "1", 1.0, []):
                with (
                    self.subTest(row=row),
                    self.assertRaisesRegex(ValidationError, "batch_and_positive_row_required"),
                ):
                    preview_recovery(batch_id="synthetic-csv", row=row)
            with self.assertRaisesRegex(ValidationError, "batch_and_positive_row_required"):
                preview_recovery(row=1)
            with self.assertRaisesRegex(ValidationError, "boolean_filter_required"):
                preview_recovery(failed_only=1)
            with self.assertRaisesRegex(ValidationError, "row_and_filter_are_exclusive"):
                preview_recovery(batch_id="synthetic-csv", row=1, failed_only=True)
            diagnose.assert_not_called()

    def test_unknown_row_and_changed_fixture_contract_fail_closed(self):
        with self.assertRaisesRegex(ValidationError, "row_not_available"):
            preview_recovery(batch_id="synthetic-csv", row=5)
        with patch("apps.fast8_intake_recovery.services.synthetic_inputs", return_value=()):
            with self.assertRaisesRegex(ValidationError, "fixture_contract_changed"):
                preview_recovery()

    def test_deterministic_detached_reports_and_no_io_or_submission(self):
        with (
            patch.object(Path, "open", side_effect=AssertionError("filesystem IO")),
            patch.object(socket, "socket", side_effect=AssertionError("network IO")),
            patch.object(sqlite3, "connect", side_effect=AssertionError("database IO")),
        ):
            first = preview_recovery()
            baseline = first.json_bytes()
            detached = first.report
            detached["rows"][0]["original"]["question"] = "changed"
            detached["inputs"].clear()
            self.assertEqual(first.json_bytes(), baseline)
            self.assertEqual(preview_recovery().json_bytes(), baseline)
        self.assertIn("OWNER_APPROVAL_PENDING", first.preview_ar())

    def test_adversarial_parse_failures_preserve_upstream_batch_codes_without_salvage(self):
        # Explicit fabricated bytes; no fixtures/files are written or accepted by the public API.
        cases = (
            (".csv", b'external_id,question\r\nSYN,"unterminated\r\n'),
            (".json", b'[{"external_id":"SYN","external_id":"OTHER"}]'),
            (".jsonl", b'{"external_id":"SYN"}\r\n{"broken":\r\n'),
            (".json", b'[{"question":"\\ud800"}]'),
            (".json", b"\xff[]"),
        )
        for suffix, raw in cases:
            with self.subTest(suffix=suffix, raw=raw):
                upstream = diagnose_batches(
                    [PreparedInput("synthetic-adversarial", raw, suffix)],
                    synthetic_fixtures_only=True,
                )
                result = _project(upstream, batch_id=None, row=None, failed_only=False)
                self.assertTrue(result.has_failures)
                self.assertEqual(result.report["rows"], [])
                self.assertEqual(result.report["inputs"], upstream.report["inputs"])
                self.assertEqual(
                    result.report["batch_failures"][0]["error_code"], "MALFORMED_INPUT"
                )
                self.assertEqual(base64.b64decode(result.report["inputs"][0]["raw_base64"]), raw)
                self.assertEqual(
                    result.report["inputs"][0]["input_sha256"], hashlib.sha256(raw).hexdigest()
                )

    def test_adversarial_bom_blank_lines_missing_cells_and_json_rejected_values(self):
        cases = (
            (".csv", b"\xef\xbb\xbfexternal_id,question\r\n\r\nSYN\r\n", "csv_missing_cell", 1),
            (".jsonl", b"\xef\xbb\xbf\r\nnull\r\n\r\n42\r\n", "record_must_be_object", 2),
            (".json", b"\xef\xbb\xbf[null,42]", "record_must_be_object", 2),
        )
        for suffix, raw, code, count in cases:
            with self.subTest(suffix=suffix):
                diagnostic = diagnose_batches(
                    [PreparedInput("synthetic-adversarial", raw, suffix)],
                    synthetic_fixtures_only=True,
                )
                result = _project(diagnostic, batch_id=None, row=None, failed_only=False).report
                self.assertEqual(len(result["rows"]), count)
                self.assertEqual([r["row"] for r in result["rows"]], list(range(1, count + 1)))
                for row in result["rows"]:
                    self.assertIn(code, [d["code"] for d in row["recommendations"]])
                    span = row["provenance"]
                    self.assertEqual(
                        base64.b64decode(span["raw_base64"]),
                        raw[span["byte_start"] : span["byte_end"]],
                    )
                    self.assertEqual(span["input_sha256"], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
