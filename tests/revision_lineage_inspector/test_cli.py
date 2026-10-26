"""Executable CLI evidence, subprocess isolated with no Django settings/database."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tools.revision_lineage_inspector.fixtures import SCENARIOS

ROOT = Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ)
        env.pop("DJANGO_SETTINGS_MODULE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.revision_lineage_inspector", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=20,
        )

    def test_all_synthetic_scenarios_have_expected_exit_and_json(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.run_cli("--synthetic-fixtures-only", "--scenario", scenario)
                expected = 0 if scenario in ("consistent", "missing-workflow") else 1
                self.assertEqual(result.returncode, expected, result.stderr.decode())
                data = json.loads(result.stdout)
                self.assertEqual(data["scenario"], scenario)
                self.assertEqual(len(data["source_payload_sha256"]), 64)
                self.assertLess(len(result.stdout), 65536)
                self.assertEqual(result.stderr, b"")

    def test_cli_bytes_repeat_exactly(self):
        self.assertEqual(
            self.run_cli("--synthetic-fixtures-only").stdout,
            self.run_cli("--synthetic-fixtures-only").stdout,
        )

    def test_acknowledgement_required_and_external_input_unsupported(self):
        for args in ((), ("--synthetic-fixtures-only", "--input", "private.json")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
