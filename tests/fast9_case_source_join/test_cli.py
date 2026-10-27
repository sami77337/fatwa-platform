import json
import os
import subprocess
import sys
from unittest import TestCase


class CliTests(TestCase):
    def run_cli(self, *args):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
        env.pop("DJANGO_SETTINGS_MODULE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast9_case_source_join", *args],
            capture_output=True,
            env=env,
            timeout=20,
        )

    def test_default_requires_opt_in_and_refuses_paths_or_extra_flags(self):
        for args in (
            (),
            ("--synthetic-fixtures-only", "--input", "private.json"),
            ("--synthetic-fixtures-only", "--synthetic"),
        ):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")

    def test_deterministic_cli_without_catalog_is_disconnected(self):
        result = self.run_cli("--synthetic-fixtures-only")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["status"], "NOT_CONNECTED")
        self.assertIsNone(payload["result"]["join"])
        self.assertEqual(payload["database_catalog"], "NOT_RUN")

    def test_explicit_synthetic_catalog_has_exact_fixture_identity_and_repeatable_bytes(self):
        args = ("--synthetic-fixtures-only", "--catalog", "synthetic")
        first, second = self.run_cli(*args), self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["fixture_id"], "fast9-case-source-join-synthetic-v1")
        self.assertEqual(len(payload["fixture_sha256"]), 64)
        self.assertEqual(payload["result"]["status"], "VERIFIED_TECHNICAL")
        self.assertEqual(payload["result"]["owner_source"], "NOT_CONNECTED")
        self.assertEqual(payload["result"]["join"]["evidence"]["printed_page"], 7)

    def test_original_second_case_uses_its_own_row_and_occurrence(self):
        result = self.run_cli(
            "--synthetic-fixtures-only", "--catalog", "synthetic", "--case-key", "intake-7"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        joined = json.loads(result.stdout)["result"]["join"]
        self.assertEqual(joined["case_identity"]["case_key"], "intake-7")
        self.assertEqual(joined["verified_identity"]["source_id"], "wave7-title-2")
        self.assertEqual(joined["evidence"]["printed_page"], 8)

    def test_unknown_key_is_not_replaced_by_default_case(self):
        result = self.run_cli(
            "--synthetic-fixtures-only", "--catalog", "synthetic", "--case-key", "unknown"
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["result"]["status"], "NOT_CONNECTED")
