"""Collection isolation, resource bounds and real offline command coverage."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline.batches import PreparedInput, prepare_batches


def row(identity="synthetic-1", **changes):
    return {
        "external_id": identity,
        "question": "  synthetic question  ",
        "prepared_clip_url": "https://example.invalid/finished.mp4",
        **changes,
    }


def source(batch_id, *rows, suffix=".json"):
    raw = json.dumps(list(rows), ensure_ascii=False).encode("utf-8")
    return PreparedInput(batch_id, raw, suffix)


class CollectionTests(unittest.TestCase):
    def prepare(self, *inputs):
        return prepare_batches(inputs, synthetic_fixtures_only=True)

    def test_independent_malformed_input_keeps_valid_files_and_source_hash(self):
        first = source("first", row())
        bad = PreparedInput("bad", b'{"secret-content', ".json")
        result = self.prepare(first, bad, source("last", row("synthetic-2")))
        self.assertEqual([entry.batch_id for entry in result.batches], ["first", "bad", "last"])
        self.assertEqual(result.batches[0].input_sha256, hashlib.sha256(first.raw).hexdigest())
        self.assertEqual(result.report["batches"][1]["status"], "ERROR")
        self.assertEqual(result.batches[1].error_code, "MALFORMED_INPUT")
        self.assertEqual(result.workbench_summary()["draft_count"], 2)
        self.assertTrue(result.has_errors)
        self.assertNotIn(b"secret-content", result.json_bytes())

    def test_cross_file_duplicates_block_all_occurrences_without_altering_sources(self):
        original = row()
        result = self.prepare(source("a", original), source("b", original, row("unique")))
        self.assertEqual(result.workbench_summary()["record_count"], 3)
        self.assertEqual(result.workbench_summary()["draft_count"], 1)
        self.assertEqual(result.workbench_summary()["status_counts"]["blocked-invalid"], 2)
        for entry in result.batches:
            item = entry.batch.report["items"][0]
            self.assertEqual(item["original"], original)
            self.assertIsNone(item["draft"])
            self.assertIn(
                {"field": "external_id", "code": "duplicate_id", "severity": "error"},
                item["findings"],
            )
        self.assertEqual(len(result.batches[0].batch.drafts), 0)
        self.assertEqual(len(result.batches[1].batch.drafts), 1)
        self.assertEqual(result.batches[1].batch.report["summary"]["ready-for-editor"], 1)
        self.assertEqual(result.batches[0].batch.report["workbench"]["draft_count"], 0)
        self.assertEqual(result.batches[1].batch.report["workbench"]["draft_count"], 1)

    def test_existing_invalid_row_participates_in_cross_file_duplicate_detection(self):
        result = self.prepare(source("bad", row(prepared_clip_url="bad")), source("good", row()))
        self.assertEqual(result.workbench_summary()["draft_count"], 0)
        self.assertEqual(result.workbench_summary()["status_counts"]["blocked-invalid"], 2)

    def test_repeated_id_within_single_file_does_not_add_duplicate_findings(self):
        result = self.prepare(source("a", row(), row()), source("b", row()))
        for entry in result.batches:
            for item in entry.batch.report["items"]:
                self.assertEqual(sum(f["code"] == "duplicate_id" for f in item["findings"]), 1)

    def test_summary_rows_keep_batch_identity_and_review_only_is_not_error(self):
        result = self.prepare(source("pending", row(prepared_clip_url="")))
        summary = result.workbench_summary()
        self.assertEqual(summary["batch_count"], 1)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["record_count"], 1)
        self.assertEqual(summary["draft_count"], 0)
        self.assertEqual(summary["rows"][0]["batch_id"], "pending")
        self.assertFalse(result.has_errors)
        self.assertEqual(
            result.json_bytes(),
            self.prepare(source("pending", row(prepared_clip_url=""))).json_bytes(),
        )

    def test_explicit_synthetic_guard_applies_to_empty_collection(self):
        for flag in (False, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(ValidationError):
                prepare_batches([], synthetic_fixtures_only=flag)

    def test_batch_ids_are_exact_bounded_unicode_and_unique(self):
        for identity in ("", " a", "a ", "a\n", "a\x7f", "a\u200b", "\ud800", "x" * 101, 1):
            with self.subTest(identity=repr(identity)), self.assertRaises(ValidationError):
                self.prepare(PreparedInput(identity, b"[]", ".json"))
        with self.assertRaises(ValidationError):
            self.prepare(source("same", row()), source("same", row("other")))

    def test_input_types_suffix_and_combined_byte_bounds(self):
        for raw, suffix in (("[]", ".json"), (b"[]", ".txt"), (b"[]", ".JSON")):
            with self.subTest(raw=raw, suffix=suffix), self.assertRaises(ValidationError):
                self.prepare(PreparedInput("a", raw, suffix))
        with self.assertRaises(ValidationError):
            self.prepare(
                PreparedInput("a", b"x" * 500_001, ".json"),
                PreparedInput("b", b"x" * 500_000, ".json"),
            )

    def test_combined_row_and_input_bounds(self):
        with self.assertRaises(ValidationError):
            self.prepare(
                source("a", *(row(str(i)) for i in range(501))),
                source("b", *(row(str(i + 501)) for i in range(500))),
            )
        with self.assertRaises(ValidationError):
            self.prepare(*(PreparedInput(str(i), b"[]", ".json") for i in range(1001)))

    def test_all_supported_file_formats(self):
        result = self.prepare(
            source("json", row("a")),
            PreparedInput("lines", json.dumps(row("b")).encode(), ".jsonl"),
            PreparedInput(
                "csv",
                b"external_id,question,prepared_clip_url\nc,synthetic,https://example.invalid/finished.mp4\n",
                ".csv",
            ),
        )
        self.assertEqual(result.workbench_summary()["draft_count"], 3)
        self.assertFalse(result.has_errors)


class FileCommandTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "apps.prepared_pipeline", *map(str, args)],
            capture_output=True,
            timeout=15,
            check=False,
        )

    def test_inline_example_remains_available(self):
        result = self.run_cli("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema"], "fatwa.prepared-pipeline.report.v1")

    def test_files_require_synthetic_acknowledgement(self):
        result = self.run_cli("--json", "nonexistent.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"--synthetic-fixtures-only", result.stderr)

    def test_real_files_isolate_bad_file_and_detect_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.json"
            second = Path(directory) / "b.jsonl"
            bad = Path(directory) / "bad.json"
            first.write_bytes(source("unused", row()).raw)
            second.write_text(json.dumps(row()), encoding="utf-8")
            bad.write_bytes(b"{")
            result = self.run_cli("--json", "--synthetic-fixtures-only", first, bad, second)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["record_count"], 2)
            self.assertEqual(report["summary"]["draft_count"], 0)
            self.assertEqual(report["summary"]["error_count"], 1)
            self.assertEqual(report["summary"]["status_counts"]["blocked-invalid"], 2)
            self.assertEqual(
                result.stdout,
                self.run_cli("--json", "--synthetic-fixtures-only", first, bad, second).stdout,
            )
            self.assertEqual(
                sorted(path.name for path in Path(directory).iterdir()),
                ["a.json", "b.jsonl", "bad.json"],
            )

    def test_same_filename_and_unreadable_input_are_reported_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "sample.json"
            valid.write_bytes(source("unused", row(prepared_clip_url="")).raw)
            review = self.run_cli("--synthetic-fixtures-only", valid)
            self.assertEqual(review.returncode, 0, review.stderr)
            result = self.run_cli(
                "--synthetic-fixtures-only", valid, valid, Path(directory) / "missing.json"
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(len(report["batches"]), 3)
            self.assertEqual(report["batches"][2]["error_code"], "SOURCE_READ_FAILED")
            self.assertEqual(len({entry["batch_id"] for entry in report["batches"]}), 3)

    def test_oversized_input_is_bounded_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.json"
            path.write_bytes(b" " * 1_000_001)
            result = self.run_cli("--json", "--synthetic-fixtures-only", path)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "ERROR")
