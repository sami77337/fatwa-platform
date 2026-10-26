"""Subprocess-level offline smoke and refusal evidence."""

import json
import subprocess
import sys
from unittest import TestCase

from tools.fiqh_reading_trail.fixtures import FIXTURE_ID, fixture_sha256


class CliTests(TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_fiqh_navigation", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_offline_fixture_identity_and_research_return(self):
        result = self.run_cli("--synthetic-fixtures-only", "--from-reference")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["fixture_id"], FIXTURE_ID)
        self.assertEqual(payload["fixture_sha256"], fixture_sha256())
        self.assertEqual(payload["database_catalog"], "NOT_RUN")
        self.assertEqual(payload["source_acceptance"], "NOT_RUN")
        self.assertEqual(payload["result"]["trail"]["status"], "verified")
        self.assertTrue(payload["result"]["trail"]["research_return_url"])

    def test_flag_required_and_file_or_network_input_unsupported(self):
        for args in ((), ("--synthetic-fixtures-only", "--archive", "secret.zip")):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_unknown_heading_produces_closed_nonzero_result(self):
        result = self.run_cli("--synthetic-fixtures-only", "--source-row-id", "999")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["result"]["edition_title"])
        self.assertIsNone(payload["result"]["trail"]["current"])
