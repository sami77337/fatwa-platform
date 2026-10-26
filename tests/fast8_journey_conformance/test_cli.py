import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from apps.fast8_journey_conformance.services import default_contract

ROOT = Path(__file__).resolve().parents[2]


class CLITests(TestCase):
    def run_cli(self, *args, data=None):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_journey_conformance", *args],
            input=data,
            capture_output=True,
            cwd=ROOT,
            env={**os.environ, "FATWA_PRODUCTION": "0"},
            timeout=30,
        )

    def test_selected_scenario_utf8_json_and_truthful_execution(self):
        result = self.run_cli("--synthetic-fixtures-only", "--scenario", "batch-synthetic-csv-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data["scenarios"]), 1)
        self.assertEqual(data["execution"]["http"], "NOT_RUN")
        self.assertEqual(data["scenarios"][0]["anchor"]["identity"]["row_ordinal"], 1)

    def test_missing_connection_has_nonzero_distinct_exit_and_machine_report(self):
        data = json.loads(default_contract())
        data["scenarios"] = [data["scenarios"][-1]]
        data["scenarios"][0]["required"].append("stock_export")
        result = self.run_cli(
            "--synthetic-fixtures-only", "--contract-stdin", data=json.dumps(data).encode()
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "NOT_CONNECTED")

    def test_guard_unknown_arguments_and_stale_pins_emit_no_passing_report(self):
        data = json.loads(default_contract())
        data["scenarios"][0]["anchor"]["packet_sha256"] = "SENSITIVE_SYNTHETIC_MARKER"
        for args, raw, code in (
            ([], None, 2),
            (["--synthetic-fixtures-only", "--file=SENSITIVE_SYNTHETIC_MARKER"], None, 2),
            (["--synthetic-fixtures-only", "--scenario", "SENSITIVE_SYNTHETIC_MARKER"], None, 1),
            (["--synthetic-fixtures-only", "--contract-stdin"], json.dumps(data).encode(), 1),
            (["--synthetic-fixtures-only", "--contract-stdin"], b"x" * 65537, 1),
        ):
            with self.subTest(args=args):
                result = self.run_cli(*args, data=raw)
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"SENSITIVE_SYNTHETIC_MARKER", result.stderr)
