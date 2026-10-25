"""Exercise the real offline command and deterministic reconciliation bundle."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.content_intake.diagnostic_cli import _check_artifact

ROOT = Path(__file__).resolve().parents[2]


class DiagnosticCommandTests(unittest.TestCase):
    def test_bundle_verification_reads_only_expected_length_plus_one(self):
        test = self

        class BoundedRead(io.BytesIO):
            def read(self, size=-1):
                test.assertEqual(size, 4)
                return super().read(size)

        for raw, expected in ((b"abc", True), (b"abc" + b"x" * 10000, False)):
            with patch.object(Path, "open", return_value=BoundedRead(raw)):
                self.assertEqual(_check_artifact(Path("synthetic"), b"abc"), expected)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tools.content_intake", "diagnose", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def test_acknowledgement_required_and_no_payload_paths_in_errors(self):
        result = self.run_cli("--batch", "a", "absent-sensitive-name.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"--synthetic-fixtures-only", result.stderr)
        result = self.run_cli(
            "--synthetic-fixtures-only", "--batch", "a", "absent-sensitive-name.json"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "LOCAL_FILE_OPERATION_FAILED")
        self.assertNotIn(b"sensitive-name", result.stdout)

    def test_export_recheck_preview_and_tamper_detection_without_source_changes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/content_intake") as directory:
            path = Path(directory) / "synthetic.jsonl"
            raw = (
                json.dumps(
                    dict(
                        external_id="s",
                        question=" سُؤالٌ اصطناعيّ ",
                        prepared_clip_url="https://example.invalid/s.mp4",
                        reference_links=[dict(source_id="s", heading_id="h")],
                    ),
                    ensure_ascii=False,
                ).encode()
                + b"\r\n"
            )
            path.write_bytes(raw)
            bundle = Path(directory) / "bundle"
            args = ("--synthetic-fixtures-only", "--batch", "a", path, "--source-id", "s")
            result = self.run_cli(*args, "--export-bundle", bundle)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((bundle / "diagnostics.json").read_bytes(), result.stdout)
            check = self.run_cli(*args, "--check-bundle", bundle)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertEqual(check.stdout, result.stdout)
            preview = self.run_cli(*args, "--preview")
            self.assertEqual(preview.returncode, 0)
            self.assertIn("الدفعة a، الصف 1", preview.stdout.decode())
            self.assertIn(b"NOT_DEPLOYED", preview.stdout)
            again = self.run_cli(*args, "--export-bundle", bundle)
            self.assertEqual(again.returncode, 1)  # Never overwrite.
            (bundle / "rows.jsonl").write_bytes(b"tampered\n")
            changed = self.run_cli(*args, "--check-bundle", bundle)
            self.assertEqual(changed.returncode, 1)
            self.assertEqual(
                json.loads(changed.stdout)["error_code"], "bundle: deterministic_output_mismatch"
            )
            self.assertEqual(path.read_bytes(), raw)
            selected = self.run_cli(*args, "--show-row", "a", "1")
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertIn("الدفعة a، الصف 1", selected.stdout.decode())
            for batch_id, ordinal in (("a", "0"), ("a", "bad"), ("missing", "1")):
                bad_selection = self.run_cli(*args, "--show-row", batch_id, ordinal)
                self.assertEqual(bad_selection.returncode, 1)
                self.assertIn("navigation:", json.loads(bad_selection.stdout)["error_code"])

    def test_missing_expected_batch_and_empty_inventory_are_actionable(self):
        result = self.run_cli(
            "--synthetic-fixtures-only", "--expect-batch", "missing", "--empty-source-inventory"
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["missing_batch_count"], 1)
        self.assertEqual(report["inventory"]["available_source_ids"], [])
        self.assertIn("وفّر", report["collection_diagnostics"][0]["recovery_ar"])

    def test_aggregate_input_bound_and_export_destination_guard(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/content_intake") as directory:
            path = Path(directory) / "synthetic.json"
            path.write_bytes(b"[]" + b" " * 500_000)
            result = self.run_cli(
                "--synthetic-fixtures-only", "--batch", "a", path, "--batch", "b", path
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("input_byte_limit_exceeded", json.loads(result.stdout)["error_code"])
            result = self.run_cli(
                "--synthetic-fixtures-only", "--expect-batch", "missing", "--export-bundle", ROOT
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                json.loads(result.stdout)["error_code"],
                "bundle: new_directory_beneath_cwd_required",
            )
