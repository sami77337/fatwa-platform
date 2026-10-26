"""Offline process boundary using exclusively fabricated manual transcript spans."""

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def synthetic_rows():
    common = dict(
        source_id="fast8-cli-fabricated-source",
        pair_id="pair-1",
        provenance="manually segmented fabricated CLI fixture; no real case",
        fabricated=True,
    )
    return [
        dict(
            common,
            segment_id="question-1",
            kind="question",
            start_ms=11,
            end_ms=1001,
            text="  سُؤالٌ مُختلَقٌ\r\nلاختبار الطابور فقط؟  ",
        ),
        dict(
            common,
            segment_id="answer-1",
            kind="answer",
            start_ms=1001,
            end_ms=2057,
            text="  جوابٌ مُختلَقٌ\r\nدليلُ مصدرٍ فقط، وليس فتوى.  ",
        ),
    ]


def nested_values(value):
    if isinstance(value, dict):
        for member in value.values():
            yield from nested_values(member)
    elif isinstance(value, list):
        for member in value:
            yield from nested_values(member)
    else:
        yield value


class TranscriptQueueCLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_transcript_queue", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def assert_safe_failure(self, result, code, status=1):
        self.assertEqual(result.returncode, status)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, (code + "\n").encode())

    def test_attestation_is_required_before_reading_any_input(self):
        self.assert_safe_failure(
            self.run_cli("never-read-private-path.json"), "SYNTHETIC_FIXTURES_REQUIRED", 2
        )

    def test_argument_errors_do_not_echo_submitted_values(self):
        for args in (
            (),
            ("private-path.json", "--export", "private-value"),
            ("private-path.json", "--unknown-private-option"),
            ("private-path.json", "--synthetic-fixtures"),
        ):
            with self.subTest(args=args):
                self.assert_safe_failure(self.run_cli(*args), "ARGUMENTS_INVALID", 2)

    def test_nonlocal_and_device_paths_fail_without_reading(self):
        for path in (
            r"\\private-server\share\input.json",
            "//private-server/share/input.json",
            r"\\?\C:\private.json",
            r"\\.\NUL",
            "C:private.json",
            "NUL.json",
            "https://example.invalid/private.json",
            "file:///private.json",
        ):
            with self.subTest(path=path):
                self.assert_safe_failure(
                    self.run_cli(path, "--synthetic-fixtures-only"), "LOCAL_FILE_READ_FAILED"
                )

    def test_missing_file_and_directory_diagnostics_are_generic(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (directory, Path(directory) / "private-missing.json"):
                with self.subTest(path=path):
                    self.assert_safe_failure(
                        self.run_cli(path, "--synthetic-fixtures-only"), "LOCAL_FILE_READ_FAILED"
                    )

    def test_report_retains_exact_text_hashes_and_milliseconds_without_writes(self):
        rows = synthetic_rows()
        raw = json.dumps(rows, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fabricated.json"
            path.write_bytes(raw)
            before = path.stat().st_mtime_ns
            first = self.run_cli(path, "--synthetic-fixtures-only")
            second = self.run_cli(path, "--synthetic-fixtures-only", "--export", "report")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stderr, b"")
            self.assertEqual(first.stdout, second.stdout)
            values = list(nested_values(json.loads(first.stdout)))
            for expected in (
                rows[0]["text"],
                rows[1]["text"],
                rows[0]["source_id"],
                "pair-1",
                "question-1",
                "answer-1",
                11,
                1001,
                2057,
                hashlib.sha256(raw).hexdigest(),
                "EPHEMERAL",
            ):
                self.assertIn(expected, values)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_prepared_export_contains_question_only_with_no_invented_enrichment(self):
        rows = synthetic_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fabricated.json"
            path.write_bytes(json.dumps(rows, ensure_ascii=False).encode())
            result = self.run_cli(path, "--synthetic-fixtures-only", "--export", "prepared")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared["schema"], "fatwa.prepared-intake.v1")
        self.assertEqual(len(prepared["items"]), 1)
        item = prepared["items"][0]
        self.assertEqual(item["question"], rows[0]["text"])
        self.assertEqual(item["prepared_clip_url"], "")
        self.assertEqual(item["staff_notes"], "")
        self.assertEqual(item["reference_links"], [])
        self.assertNotIn(rows[1]["text"], list(nested_values(prepared)))

    def test_csv_and_jsonl_preserve_same_questions_and_source_identities(self):
        rows = synthetic_rows()
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(dict(row, fabricated="true") for row in rows)
        payloads = {
            ".json": json.dumps(rows, ensure_ascii=False),
            ".csv": stream.getvalue(),
            ".jsonl": "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        }
        exports = []
        with tempfile.TemporaryDirectory() as directory:
            for suffix, payload in payloads.items():
                with self.subTest(suffix=suffix):
                    path = Path(directory) / ("fabricated" + suffix)
                    path.write_bytes(payload.encode())
                    result = self.run_cli(path, "--synthetic-fixtures-only", "--export", "prepared")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    exports.append(result.stdout)
        self.assertEqual(len(exports), 3)
        self.assertEqual(exports[0], exports[1])
        self.assertEqual(exports[0], exports[2])

    def test_invalid_or_oversized_input_never_emits_partial_queue_or_submitted_text(self):
        rows = synthetic_rows()
        overlapping = [rows[0], dict(rows[1], start_ms=1000)]
        not_fabricated = [dict(rows[0], fabricated=False)]
        orphan = [rows[1]]
        payloads = (
            b"not-json-private-value",
            b"[NaN]",
            b'["\\ud800"]',
            b" " * 1_000_001,
            json.dumps(overlapping, ensure_ascii=False).encode(),
            json.dumps(not_fabricated, ensure_ascii=False).encode(),
            json.dumps(orphan, ensure_ascii=False).encode(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-fabricated.json"
            for raw in payloads:
                with self.subTest(size=len(raw)):
                    path.write_bytes(raw)
                    self.assert_safe_failure(
                        self.run_cli(path, "--synthetic-fixtures-only"),
                        "TRANSCRIPT_QUEUE_VALIDATION_FAILED",
                    )

    def test_symlink_leaf_and_parent_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "actual"
            target.mkdir()
            path = target / "fabricated.json"
            path.write_bytes(json.dumps(synthetic_rows(), ensure_ascii=False).encode())
            try:
                (root / "leaf.json").symlink_to(path)
                (root / "parent").symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"OS does not permit unprivileged symlinks: {exc.errno}")
            for candidate in (root / "leaf.json", root / "parent" / path.name):
                with self.subTest(candidate=candidate):
                    self.assert_safe_failure(
                        self.run_cli(candidate, "--synthetic-fixtures-only"),
                        "LOCAL_FILE_READ_FAILED",
                    )

    @unittest.skipUnless(os.name == "nt", "Windows junction filesystem contract")
    def test_junction_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "actual"
            target.mkdir()
            path = target / "fabricated.json"
            path.write_bytes(json.dumps(synthetic_rows(), ensure_ascii=False).encode())
            junction = root / "parent"
            # Fixed fixture paths only; cmd is required for mklink, never for deletion.
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(created.returncode, 0, "Unable to create local junction fixture")
            self.assertTrue(junction.is_junction())
            self.assert_safe_failure(
                self.run_cli(junction / path.name, "--synthetic-fixtures-only"),
                "LOCAL_FILE_READ_FAILED",
            )
