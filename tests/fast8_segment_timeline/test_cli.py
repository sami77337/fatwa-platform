"""Exercise the offline CLI process boundary; no real media or network."""

import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fast8_segment_timeline.test_service import answer, encode, row

ROOT = Path(__file__).resolve().parents[2]


class TimelineCLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_segment_timeline", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def test_attestation_is_required_before_file_access(self):
        result = self.run_cli("fabricated-missing.json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"fabricated-missing", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_deterministic_report_hash_and_input_unchanged(self):
        raw = encode([row(), answer()])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.json"
            path.write_bytes(raw)
            args = (path, "--synthetic-fixtures-only")
            first, second = self.run_cli(*args), self.run_cli(*args)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stderr, b"")
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(
                json.loads(first.stdout)["input_sha256"], hashlib.sha256(raw).hexdigest()
            )
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_manual_exports_preserve_exact_question_and_crlf(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.csv"
            path.write_bytes(encode([row(), answer()], ".csv"))
            for export in ("cues-json", "cues-csv"):
                with self.subTest(export=export):
                    result = self.run_cli(path, "--synthetic-fixtures-only", "--export", export)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if export == "cues-json":
                        value = json.loads(result.stdout)
                        self.assertEqual(value["mode"], "MANUAL")
                        cues = value["cues"]
                    else:
                        cues = list(
                            csv.DictReader(io.StringIO(result.stdout.decode("utf-8"), newline=""))
                        )
                        self.assertEqual(cues[0]["mode"], "MANUAL")
                    self.assertEqual(cues[0]["question_label"], row()["text"])
                    self.assertEqual(cues[1]["question_label"], row()["text"])

    def test_temporal_errors_emit_report_but_block_all_cue_output(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.json"
            path.write_bytes(encode([row(end_ms=0)]))
            report = self.run_cli(path, "--synthetic-fixtures-only")
            self.assertEqual(report.returncode, 1)
            self.assertIn(
                "invalid_interval", {f["code"] for f in json.loads(report.stdout)["findings"]}
            )
            for export in ("cues-json", "cues-csv"):
                result = self.run_cli(path, "--synthetic-fixtures-only", "--export", export)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)

    def test_declared_duration_file_is_enforced(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.json"
            duration = Path(directory) / "duration.json"
            path.write_bytes(encode([row()]))
            duration.write_bytes(b'{"fabricated-video":1000}')
            result = self.run_cli(path, "--synthetic-fixtures-only", "--durations", duration)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "duration_exceeded", {f["code"] for f in json.loads(result.stdout)["findings"]}
            )

    def test_null_or_malformed_duration_file_is_not_treated_as_absent(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.json"
            duration = Path(directory) / "duration.json"
            path.write_bytes(encode([row()]))
            for raw in (b"null", b"[]", b"{", b'{"fabricated-video":true}'):
                with self.subTest(raw=raw):
                    duration.write_bytes(raw)
                    result = self.run_cli(
                        path, "--synthetic-fixtures-only", "--durations", duration
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b"")
                    self.assertNotIn(b"Traceback", result.stderr)

    def test_invalid_source_identity_with_duration_does_not_crash_or_echo_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "fabricated.json"
            duration = Path(directory) / "duration.json"
            path.write_bytes(encode([row(source_id=["fabricated-secret-sentinel"])]))
            duration.write_bytes(b'{"fabricated-video":1001}')
            result = self.run_cli(path, "--synthetic-fixtures-only", "--durations", duration)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"Traceback", result.stderr)
            self.assertNotIn(b"fabricated-secret-sentinel", result.stderr)

    def test_malformed_or_nonfabricated_data_never_leaks_partial_export(self):
        for raw in (b"{", encode([row(), answer(fabricated=False)]), b" " * 1000001):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                path = Path(directory) / "fabricated.json"
                path.write_bytes(raw)
                result = self.run_cli(path, "--synthetic-fixtures-only")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertNotIn(str(path).encode(), result.stderr)

    def test_nonlocal_device_and_drive_relative_paths_fail_without_echo(self):
        for path in (
            r"\\private-server\share\input.json",
            "//private-server/share/input.json",
            r"\\?\C:\private.json",
            r"\\.\NUL",
            "C:private.json",
            "NUL.json",
        ):
            with self.subTest(path=path):
                result = self.run_cli(path, "--synthetic-fixtures-only")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(path.encode(), result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_invalid_arguments_do_not_echo_values(self):
        result = self.run_cli("fabricated.json", "--export", "fabricated-secret-sentinel")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"fabricated-secret-sentinel", result.stderr)


if __name__ == "__main__":
    unittest.main()
