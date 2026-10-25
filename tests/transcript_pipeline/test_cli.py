"""Exercise the offline process boundary with fabricated fixtures only."""

import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def synthetic_rows():
    common = dict(
        source_id="synthetic-cli",
        pair_id="pair-1",
        provenance="fabricated fixture",
        fabricated=True,
    )
    return [
        dict(
            common,
            segment_id="q-1",
            kind="question",
            start_ms=0,
            end_ms=1000,
            text="  سُؤالٌ اصطناعيّ للاختبار فقط  ",
        ),
        dict(
            common,
            segment_id="a-1",
            kind="answer",
            start_ms=1000,
            end_ms=2000,
            text="جواب اصطناعي للاختبار، وليس فتوى.",
        ),
    ]


class TranscriptCLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tools.transcript_pipeline", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def assert_safe_failure(self, result, code, status=1):
        self.assertEqual(result.returncode, status)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, (code + "\n").encode())

    def test_attestation_required_before_file_read(self):
        self.assert_safe_failure(
            self.run_cli("sensitive-missing-file.json"), "SYNTHETIC_FIXTURES_REQUIRED", 2
        )

    def test_missing_file_error_never_echoes_path(self):
        self.assert_safe_failure(
            self.run_cli("sensitive-missing-file.json", "--synthetic-fixtures-only"),
            "LOCAL_FILE_READ_FAILED",
        )

    def test_nonlocal_device_and_drive_relative_paths_are_rejected(self):
        for path in (
            r"\\private-server\share\input.json",
            "//private-server/share/input.json",
            r"\\?\C:\private.json",
            r"\\.\NUL",
            "C:private.json",
            "NUL.json",
        ):
            with self.subTest(path=path):
                self.assert_safe_failure(
                    self.run_cli(path, "--synthetic-fixtures-only"),
                    "LOCAL_FILE_READ_FAILED",
                )

    def test_directory_is_rejected_as_nonregular_input(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_safe_failure(
                self.run_cli(directory, "--synthetic-fixtures-only"),
                "LOCAL_FILE_READ_FAILED",
            )

    def test_invalid_arguments_never_echo_user_values(self):
        for args in (
            ("private.json", "--export", "private-text"),
            ("private.json", "--private-option"),
            (),
        ):
            with self.subTest(args=args):
                self.assert_safe_failure(self.run_cli(*args), "ARGUMENTS_INVALID", 2)

    def test_report_is_deterministic_utf8_and_does_not_modify_input(self):
        rows = synthetic_rows()
        raw = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_bytes(raw)
            args = (path, "--synthetic-fixtures-only")
            first = self.run_cli(*args)
            again = self.run_cli(*args, "--export", "report")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stderr, b"")
            self.assertEqual(first.stdout, again.stdout)
            json.loads(first.stdout)
            self.assertIn(rows[0]["text"].encode("utf-8"), first.stdout)
            self.assertIn(rows[1]["text"].encode("utf-8"), first.stdout)
            self.assertIn(hashlib.sha256(raw).hexdigest().encode(), first.stdout)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_prepared_export_contains_only_exact_question_and_empty_enrichment(self):
        rows = synthetic_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(path, "--synthetic-fixtures-only", "--export", "prepared")
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared["schema"], "fatwa.prepared-intake.v1")
        self.assertEqual(len(prepared["items"]), 1)
        item = prepared["items"][0]
        self.assertEqual(item["question"], rows[0]["text"])
        self.assertEqual(item["prepared_clip_url"], "")
        self.assertEqual(item["reference_links"], [])
        self.assertEqual(item["staff_notes"], "")
        self.assertNotIn(rows[1]["text"].encode("utf-8"), result.stdout)

    def test_csv_and_jsonl_inputs_are_accepted(self):
        rows = synthetic_rows()
        csv_text = io.StringIO(newline="")
        writer = csv.DictWriter(csv_text, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, "fabricated": "true"} for row in rows)
        payloads = {
            ".csv": csv_text.getvalue(),
            ".jsonl": "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        }
        with tempfile.TemporaryDirectory() as directory:
            for suffix, payload in payloads.items():
                with self.subTest(suffix=suffix):
                    path = Path(directory) / ("synthetic" + suffix)
                    path.write_text(payload, encoding="utf-8")
                    result = self.run_cli(path, "--synthetic-fixtures-only")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(rows[0]["text"].encode("utf-8"), result.stdout)

    def test_invalid_late_row_does_not_export_partial_content(self):
        rows = synthetic_rows()
        rows[1]["fabricated"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-filename.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            for export in ("report", "prepared"):
                with self.subTest(export=export):
                    self.assert_safe_failure(
                        self.run_cli(path, "--synthetic-fixtures-only", "--export", export),
                        "TRANSCRIPT_VALIDATION_FAILED",
                    )

    def test_oversized_malformed_and_unsupported_files_fail_without_export(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, raw in (
                ("oversized.json", b" " * 1_000_001),
                ("malformed.json", b'{"private-text":'),
                ("unsupported.wav", b"private-text"),
            ):
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(raw)
                    self.assert_safe_failure(
                        self.run_cli(path, "--synthetic-fixtures-only"),
                        "TRANSCRIPT_VALIDATION_FAILED",
                    )


if __name__ == "__main__":
    unittest.main()
