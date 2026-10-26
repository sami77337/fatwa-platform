import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fast8_source_preflight.fixtures import AS_OF, fixture
from tools.fast8_source_preflight.cli import main
from tools.source_readiness.cli import ReadError


class ReceiptCliTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_no_args_has_machine_readable_absence(self):
        code, report = self.invoke([])
        self.assertEqual(code, 3)
        self.assertEqual(report["owner_archives"], "NOT_SUPPLIED")

    def test_missing_pin_blocks_before_any_read(self):
        with patch("tools.fast8_source_preflight.cli.read_local") as read:
            code, report = self.invoke(["--receipt", "never-open.json"])
        read.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "BLOCKED")

    def test_reads_only_explicit_receipt_and_never_entry_paths(self):
        raw, digest = fixture()
        with patch("tools.fast8_source_preflight.cli.read_local", return_value=raw) as read:
            code, report = self.invoke(
                ["--receipt", "receipt.json", "--expected-sha256", digest, "--as-of", AS_OF]
            )
        self.assertEqual(code, 0)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[0], "receipt.json")
        self.assertEqual(report["archive_verification"], "NOT_RUN")

    def test_archive_input_owner_and_abbreviated_options_are_rejected_without_reads(self):
        for option in ("--archive", "--input", "--pinned-owner", "--rece"):
            with patch("tools.fast8_source_preflight.cli.read_local") as read:
                code, report = self.invoke([option, "never-open.zip"])
            read.assert_not_called()
            self.assertEqual(code, 2)
            self.assertNotIn("never-open", json.dumps(report))

    def test_local_read_failure_does_not_leak_path(self):
        with patch(
            "tools.fast8_source_preflight.cli.read_local",
            side_effect=ReadError("RECEIPT_UNREADABLE"),
        ):
            code, report = self.invoke(
                ["--receipt", "confidential-path", "--expected-sha256", "0" * 64, "--as-of", AS_OF]
            )
        self.assertEqual(code, 2)
        self.assertNotIn("confidential-path", json.dumps(report))

    def test_cli_end_to_end_without_any_archives(self):
        raw, digest = fixture()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic-receipt.json"
            path.write_bytes(raw)
            args = [
                sys.executable,
                "-B",
                "-m",
                "tools.fast8_source_preflight",
                "--receipt",
                str(path),
                "--expected-sha256",
                digest,
                "--as-of",
                AS_OF,
            ]
            result = subprocess.run(args, capture_output=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "RECEIPT_VERIFIED")
            self.assertEqual(report["owner_archives"], "NOT_SUPPLIED")
            self.assertEqual(result.stderr, b"")
            self.assertEqual(list(Path(temp).iterdir()), [path])
            path.write_bytes(raw + b"\r\n")
            result = subprocess.run(args, capture_output=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["reasons"], ["receipt_sha256_mismatch"])
            path.unlink()
            result = subprocess.run(args, capture_output=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["owner_archives"], "NOT_SUPPLIED")
