import json
import os
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from tests.fast9_transcript_prepared_lineage.support import FIXTURES, encode, rows
from tools.fast9_transcript_prepared_lineage.cli import main

ROOT = Path(__file__).resolve().parents[2]
COMMAND = [sys.executable, "-B", "-m", "tools.fast9_transcript_prepared_lineage"]
INPUT = str(FIXTURES / "manual-qa.json")
PINS = str(FIXTURES / "manual-qa.pins.json")


def run(*arguments):
    return subprocess.run(
        COMMAND + list(arguments),
        cwd=ROOT,
        capture_output=True,
        timeout=20,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", DJANGO_SETTINGS_MODULE="does.not.exist"),
    )


class CliTests(unittest.TestCase):
    def test_real_module_all_exports_without_django_settings(self):
        payloads = {}
        for export in ("report", "prepared", "cues", "cue-csv"):
            with self.subTest(export=export):
                result = run(INPUT, "--pins", PINS, "--synthetic-fixtures-only", "--export", export)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                payloads[export] = result.stdout
        report = json.loads(payloads["report"])
        self.assertEqual(len(report["receipts"]), 2)
        self.assertEqual(len(json.loads(payloads["prepared"])["items"]), 2)
        self.assertEqual(len(json.loads(payloads["cues"])["cues"]), 4)
        self.assertIn(b"\r\n", payloads["cue-csv"])
        from hashlib import sha256

        self.assertEqual(report["cue_csv_sha256"], sha256(payloads["cue-csv"]).hexdigest())
        self.assertEqual(report["cue_json_sha256"], sha256(payloads["cues"]).hexdigest())

    def test_guard_precedes_all_file_reads(self):
        with patch(
            "tools.fast9_transcript_prepared_lineage.cli._read_local",
            side_effect=AssertionError("read before guard"),
        ):
            self.assertEqual(main(["missing.json", "--pins", "missing.pins.json"]), 2)

    def test_explicit_guard_and_pins_are_required(self):
        for args in ((INPUT, "--pins", PINS), (INPUT, "--synthetic-fixtures-only")):
            with self.subTest(args=args):
                result = run(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")

    def test_bad_local_inputs_never_emit_partial_receipt_or_echo_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            for raw in (b'{"private-marker":', b"\xff", b"x" * 1_000_001):
                path.write_bytes(raw)
                result = run(str(path), "--pins", PINS, "--synthetic-fixtures-only")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"TRANSCRIPT_LINEAGE_VALIDATION_FAILED\n")

    def test_remote_parent_device_and_missing_paths_rejected(self):
        for value in (
            "https://example.invalid/fixture.json",
            "//server/share/input.json",
            "../manual-qa.json",
            "NUL",
            "absent-fixture.json",
        ):
            with self.subTest(value=value):
                result = run(value, "--pins", PINS, "--synthetic-fixtures-only")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")

    def test_pins_and_verification_paths_use_same_local_only_guard(self):
        for option in ("--pins", "--verify-receipt"):
            args = [INPUT, "--synthetic-fixtures-only", "--pins", PINS]
            if option == "--pins":
                args[-1] = "https://example.invalid/pins.json"
            else:
                args += [option, "https://example.invalid/receipt.json"]
            result = run(*args)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")

    def test_retained_report_replay_and_tampering(self):
        initial = run(INPUT, "--pins", PINS, "--synthetic-fixtures-only")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(initial.stdout)
            result = run(
                INPUT, "--pins", PINS, "--synthetic-fixtures-only", "--verify-receipt", str(path)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, initial.stdout)
            path.write_bytes(initial.stdout.replace(b"1023", b"1024"))
            result = run(
                INPUT, "--pins", PINS, "--synthetic-fixtures-only", "--verify-receipt", str(path)
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")

    def test_every_export_rejects_crlf_changed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            raw = encode(rows())
            pins = json.loads(Path(PINS).read_bytes())
            pins["input_sha256"] = sha256(raw).hexdigest()
            pin_path = Path(directory) / "pins.json"
            pin_path.write_bytes(json.dumps(pins).encode())
            path.write_bytes(raw)
            self.assertEqual(
                run(str(path), "--pins", str(pin_path), "--synthetic-fixtures-only").returncode, 0
            )
            path.write_bytes(raw.replace(b"\r\n", b"\n"))
            for export in ("report", "prepared", "cues", "cue-csv"):
                with self.subTest(export=export):
                    result = run(
                        str(path),
                        "--pins",
                        str(pin_path),
                        "--synthetic-fixtures-only",
                        "--export",
                        export,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b"")
