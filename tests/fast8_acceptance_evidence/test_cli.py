"""The CLI exposes only fixed synthetic execution and bounded exact replay."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from apps.fast8_acceptance_evidence.services import MAX_REPORT_BYTES

ROOT = Path(__file__).resolve().parents[2]


class CliTests(TestCase):
    def invoke(self, *args, raw=None, production="0"):
        env = {**os.environ, "FATWA_PRODUCTION": production, "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("DJANGO_SETTINGS_MODULE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_acceptance_evidence", *args],
            cwd=ROOT,
            env=env,
            input=raw,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_cli_success_means_generated_matrix_not_owner_acceptance(self):
        result = self.invoke("--synthetic-fixtures-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout, self.invoke("--synthetic-fixtures-only").stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertEqual(data["producer"]["status"], "PASS")
        self.assertIn("المالك".encode(), result.stdout)

    def test_verify_exact_matrix_and_reject_forged_owner_acceptance(self):
        raw = self.invoke("--synthetic-fixtures-only").stdout
        verified = self.invoke("--synthetic-fixtures-only", "--verify-stdin", raw=raw)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["acceptance"], "BLOCKED")
        altered = json.loads(raw)
        altered["acceptance"]["owner"] = "PASS"
        failed = self.invoke(
            "--synthetic-fixtures-only", "--verify-stdin", raw=json.dumps(altered).encode()
        )
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(json.loads(failed.stdout)["status"], "FAIL")

    def test_unknown_paths_approval_switches_and_abbreviations_are_redacted(self):
        for args in (
            (),
            ("--synthetic",),
            ("--synthetic-fixtures-only", "--approve-owner"),
            ("--synthetic-fixtures-only", "--source-zip", "private-secret.zip"),
            ("--synthetic-fixtures-only", "--output", "private-secret.json"),
        ):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["status"], "FAIL")
                self.assertNotIn(b"private-secret", result.stdout + result.stderr)
                self.assertNotIn(b"Traceback", result.stdout + result.stderr)

    def test_production_refuses_generation_and_verification(self):
        for args in (
            ("--synthetic-fixtures-only",),
            ("--synthetic-fixtures-only", "--verify-stdin"),
        ):
            result = self.invoke(*args, production="1", raw=b"private-secret")
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"private-secret", result.stdout + result.stderr)

    def test_bounded_stdin_rejects_large_and_malformed_reports(self):
        for raw in (b"x" * (MAX_REPORT_BYTES + 1), b"{", b"", b"\xff"):
            result = self.invoke("--synthetic-fixtures-only", "--verify-stdin", raw=raw)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")
