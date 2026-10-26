import json
import os
import subprocess
import sys
import unittest


class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_prepared_review", *args],
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_explicit_synthetic_ack_and_known_case_are_required(self):
        for args in (
            (),
            ("--synthetic-fixtures-only", "--case", "../../private.zip"),
            ("--synthetic-fixtures-only", "--input", "source.zip"),
        ):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")

    def test_scenario_output_is_deterministic_utf8_with_real_diagnostics(self):
        first = self.run_cli("--synthetic-fixtures-only")
        second = self.run_cli("--synthetic-fixtures-only")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(len(result["steps"]), 12)
        self.assertEqual(sum(step["accepted"] for step in result["steps"]), 5)
        self.assertEqual(result["final"]["review"], "REVIEWED_INTERNAL")
        self.assertIn("سُؤَالٌ", first.stdout.decode("utf-8"))
        self.assertEqual(result["steps"][-2]["reason"], "bridge: state_snapshot_mismatch")
        self.assertEqual(result["steps"][-1]["reason"], "bridge: source_identity_mismatch")
        self.assertEqual(result["gates"]["U03/U10"], "OWNER_APPROVAL_PENDING")

    def test_blocked_case_reports_no_fabricated_draft(self):
        result = self.run_cli("--synthetic-fixtures-only", "--case", "batch-synthetic-json-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["final"]["record"])
        self.assertEqual(sum(step["accepted"] for step in payload["steps"]), 0)

    def test_production_environment_is_rejected(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "tools.fast8_prepared_review",
                "--synthetic-fixtures-only",
            ],
            capture_output=True,
            timeout=20,
            check=False,
            env=dict(os.environ, FATWA_PRODUCTION="1"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"synthetic_development_only", result.stderr)


if __name__ == "__main__":
    unittest.main()
