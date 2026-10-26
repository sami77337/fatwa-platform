import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from tools.fiqh_reading_trail.fixtures import FIXTURE_ID, fixture_sha256


class CliTests(TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tools.fast8_case_references", *args],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_deterministic_utf8_success_with_actual_fixture_identity(self):
        args = ("--synthetic-fixtures-only", "--case", "intake-1")
        first, second = self.run_cli(*args), self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout.decode("utf-8"))
        self.assertEqual(payload["fixture"]["id"], FIXTURE_ID)
        self.assertEqual(payload["fixture"]["sha256"], fixture_sha256())
        self.assertEqual(payload["status"], "VERIFIED")

    def test_missing_and_unresolved_exit_two_with_complete_report(self):
        for key, expected in (("intake-2", "MISSING"), ("history", "INCOMPLETE")):
            result = self.run_cli("--synthetic-fixtures-only", "--case", key)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout)["status"], expected)

    def test_opt_in_required_and_unknown_arguments_do_not_echo_input(self):
        for args in (
            ("--case", "private-value"),
            ("--synthetic-fixtures-only", "--case", "intake-1", "--input", "private-value"),
        ):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"private-value", result.stderr)

    def test_unknown_case_is_closed_and_not_echoed(self):
        result = self.run_cli("--synthetic-fixtures-only", "--case", "private-value")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"private-value", result.stderr)
