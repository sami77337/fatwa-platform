import json
import os
import subprocess
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.revision_core.revision_history import HistoryDataError
from apps.workflow_invariants.engine import ReplayError, canonical_bytes, replay, scenario
from tools.workflow_invariants.cli import load_request, main


class CliTests(unittest.TestCase):
    def run_cli(self, *args, raw=None):
        return subprocess.run(
            [sys.executable, "-m", "tools.workflow_invariants", *args],
            input=raw,
            capture_output=True,
            env=dict(os.environ, PYTHONUTF8="1"),
            timeout=30,
        )

    def test_cli_utf8_exact_bytes_deterministic_and_no_django(self):
        first = self.run_cli("--scenario", "rehearsal")
        second = self.run_cli("--scenario", "rehearsal")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["owner_transitions"], "NOT_SUPPLIED")
        self.assertEqual(len(result["steps"]), 8)

    def test_stdin_and_file_fixture_match_service_and_raw_input_hash(self):
        raw = canonical_bytes(scenario("preparation"))
        result = self.run_cli("--input", "-", raw=raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["final"], replay(scenario("preparation"))["final"])
        self.assertIn("input_bytes_sha256", report)
        paths = list(Path("tools/workflow_invariants/fixtures").glob("*.json"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(json.loads(path.read_bytes()), scenario(path.stem))
                outcome = self.run_cli("--input", str(path))
                self.assertEqual(outcome.returncode, 0, outcome.stderr)

    def test_rejection_exit_policy_and_missing_file(self):
        result = self.run_cli("--scenario", "rehearsal", "--fail-on-rejection")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["invariants_passed"])
        result = self.run_cli("--input", "missing-synthetic-fixture.json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["reason"], "input: io_error")

    def test_fixture_emission_is_a_valid_command_envelope(self):
        result = self.run_cli("--scenario", "blocked", "--emit-fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), scenario("blocked"))

    def test_invalid_input_is_machine_readable_and_bounded(self):
        for raw in (
            b'{"schema":1,"schema":2}',
            b"NaN",
            b"{}",
            b"\xff",
            b"[" * 1001 + b"]" * 1001,
            b" " * 1_000_001,
            b'{"x": "\\ud800"}',
            b'{"x": 1.0}',
        ):
            with self.subTest(raw=raw[:40]):
                result = self.run_cli("--input", "-", raw=raw)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(json.loads(result.stderr)["status"], "INVALID_INPUT")
                self.assertNotIn(b"Traceback", result.stderr)

    def test_stream_reads_only_limit_plus_one(self):
        stream = BytesIO(b" " * 1_000_010)
        with self.assertRaises(ReplayError):
            load_request(stream)
        self.assertEqual(stream.tell(), 1_000_001)

    def test_history_contract_failure_returns_json_and_exit_three(self):
        stdout, stderr = BytesIO(), BytesIO()
        with (
            patch(
                "apps.workflow_invariants.engine.build_history",
                side_effect=HistoryDataError("invalid_history_content"),
            ),
            patch("sys.stdout", SimpleNamespace(buffer=stdout)),
            patch("sys.stderr", SimpleNamespace(buffer=stderr)),
        ):
            code = main(["--scenario", "preparation"])
        self.assertEqual(code, 3)
        self.assertEqual(stdout.getvalue(), b"")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"status": "INVARIANT_FAILURE", "reason": "invariant: invalid_history"},
        )

    def test_no_database_or_network_import_in_fresh_process(self):
        code = """
import sys
from apps.workflow_invariants.engine import replay, scenario
replay(scenario('rehearsal'))
assert 'django' not in sys.modules
assert 'psycopg' not in sys.modules
assert 'apps.intake_workflow.review' not in sys.modules
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
