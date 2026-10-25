"""Subprocess coverage of the explicitly synthetic, offline CLI boundary."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SyntheticCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        environment["PYTHONIOENCODING"] = "ascii"
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.policy_gap_engine", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_explicit_synthetic_acknowledgement_is_required(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"--synthetic-only", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_incomplete_or_unacknowledged_requests_are_rejected(self):
        cases = (
            ("--actor", "MUFTI", "--action", "APPROVE", "--resource", "FATWA"),
            ("--synthetic-only", "--actor", "MUFTI"),
            ("--synthetic-only", "--action", "APPROVE", "--resource", "FATWA"),
            ("--synthetic-only", "--target-state", "PUBLISHED"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)

    def test_abbreviations_and_external_file_options_are_rejected(self):
        cases = (
            ("--synthetic-on",),
            ("--synthetic-only", "--act", "MUFTI"),
            ("--synthetic-only", "--input", "policy.json"),
            ("--synthetic-only", "--policy", "policy.json"),
            ("--synthetic-only", "--output", "report.json"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, b"")

    def test_help_explains_that_success_is_not_permission(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.decode("utf-8").lower()
        self.assertIn("synthetic", output)
        self.assertIn("permission", output)
        self.assertIn("--synthetic-only", output)

    def test_default_report_is_canonical_repeatable_and_denied(self):
        first = self.run_cli("--synthetic-only")
        second = self.run_cli("--synthetic-only")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        report = json.loads(first.stdout)
        self.assertEqual(report["status"], "SYNTHETIC_EVALUATED")
        self.assertEqual(report["effect"], "DENY")
        self.assertIs(report["allowed"], False)
        expected = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self.assertEqual(first.stdout, expected.encode("utf-8"))

    def test_unknown_custom_request_is_denied_without_echoing_private_text(self):
        result = self.run_cli(
            "--synthetic-only",
            "--actor",
            "private-marker-actor-123",
            "--action",
            "private-marker-action-456",
            "--resource",
            "نص خاص private-marker-resource-789",
            "--target-state",
            "private-marker-state-012",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["effect"], "DENY")
        self.assertIs(report["allowed"], False)
        self.assertEqual(len(report["requests"]), 1)
        self.assertIs(report["requests"][0]["request"]["target_state_supplied"], True)
        self.assertNotIn(b"private-marker", result.stdout)
        self.assertEqual(result.stderr, b"")

    def test_custom_workflow_arguments_reach_the_requested_evaluation(self):
        result = self.run_cli(
            "--synthetic-only",
            "--actor",
            "MUFTI",
            "--action",
            "complete_review",
            "--resource",
            "workflow::IN_REVIEW",
            "--target-state",
            "REVIEWED_INTERNAL",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report["requests"]), 1)
        decision = report["requests"][0]
        self.assertEqual(
            decision["request"],
            {
                "actor": "MUFTI",
                "action": "complete_review",
                "resource": "workflow::IN_REVIEW",
                "target_state_supplied": True,
                "target_state_matches": True,
            },
        )
        self.assertEqual(decision["effect"], "DENY")
        self.assertIs(decision["allowed"], False)

    def test_unavailable_evidence_returns_denied_json_and_exit_three(self):
        script = """
from unittest.mock import patch
from apps.permission_lab.sources import SourceUnavailable
from tools.policy_gap_engine.__main__ import main
with patch(
    'apps.permission_lab.sources.load_inventory',
    side_effect=SourceUnavailable('private-marker-source-error'),
):
    raise SystemExit(main(['--synthetic-only']))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "EVIDENCE_UNAVAILABLE")
        self.assertEqual(report["effect"], "DENY")
        self.assertIs(report["allowed"], False)
        self.assertNotIn(b"private-marker", result.stdout)
        self.assertEqual(result.stderr, b"")

    def test_failed_adversarial_result_sets_failure_exit_code(self):
        script = """
from unittest.mock import patch
from apps.policy_gap_engine import services
from tools.policy_gap_engine.__main__ import main
report = services.build_report()
report['adversarial_checks']['status'] = 'FAIL'
with patch.object(services, 'build_report', return_value=report):
    raise SystemExit(main(['--synthetic-only']))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["adversarial_checks"]["status"], "FAIL")
        self.assertIs(report["allowed"], False)
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
