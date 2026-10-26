"""Execute the real offline CLI through UTF-8 pipes, without Django or a database."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CasePermissionCLITests(unittest.TestCase):
    def run_cli(self, *arguments, data=None):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_case_permission", *arguments],
            cwd=ROOT,
            input=data,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def receipt(self):
        result = self.run_cli(
            "--synthetic-only",
            "describe",
            "--case-key",
            "batch-synthetic-csv-1",
            "--scenario-resource",
            "synthetic::answer",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def evaluate(self, data, key="batch-synthetic-csv-1", *extra):
        return self.run_cli(
            "--synthetic-only",
            "evaluate",
            "--case-key",
            key,
            "--actor",
            "MUFTI",
            "--action",
            "synthetic::answer.create",
            "--descriptor-stdin",
            *extra,
            data=data,
        )

    def test_describe_then_evaluate_uses_exact_utf8_receipt(self):
        receipt = self.receipt()
        self.assertIn("دفعة".encode(), receipt)
        self.assertEqual(json.loads(receipt)["batch_id"], "synthetic-csv")
        result = self.evaluate(receipt)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["context_status"], "VERIFIED")
        self.assertEqual(report["effect"], "DENY")
        self.assertIs(report["allowed"], False)
        self.assertEqual(report["policy_status"], "POLICY_PENDING")
        self.assertEqual(report["evidence_status"], "MISSING_EVIDENCE")
        self.assertEqual(report["gates"]["deployment"], "NOT_DEPLOYED")
        self.assertEqual(result.stderr, b"")

    def test_cross_case_and_stale_payload_exit_nonzero(self):
        receipt = self.receipt()
        result = self.evaluate(receipt, "history")
        self.assertEqual(result.returncode, 3)
        self.assertIn("CROSS_CASE_SUBSTITUTION", json.loads(result.stdout)["reason_codes"])
        value = json.loads(receipt)
        value["payload_sha256"] = "0" * 64
        result = self.evaluate(json.dumps(value).encode())
        self.assertEqual(result.returncode, 3)
        self.assertIn("STALE_DESCRIPTOR", json.loads(result.stdout)["reason_codes"])

    def test_duplicate_cases_are_rejected_in_describe(self):
        result = self.run_cli(
            "--synthetic-only", "describe", "--case-key", "batch-synthetic-json-1"
        )
        self.assertEqual(result.returncode, 3)
        report = json.loads(result.stdout)
        self.assertIn("DUPLICATE_EXTERNAL_ID", report["reason_codes"])
        self.assertIs(report["allowed"], False)
        self.assertIsNone(report["descriptor"])

    def test_cli_requires_opt_in_exact_arguments_and_receipt(self):
        for arguments in (
            ("describe", "--case-key", "history"),
            ("--synthetic-only", "describe", "--case", "history"),
            ("--synthetic-only", "describe", "--case-key", "history", "--source", "private-marker"),
            (
                "--synthetic-only",
                "evaluate",
                "--case-key",
                "history",
                "--actor",
                "MUFTI",
                "--action",
                "approve",
            ),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(b"private-marker", result.stdout + result.stderr)

    def test_invalid_oversized_and_non_utf8_receipts_are_closed_without_echo(self):
        for data in (b"private-marker", b"x" * 8193, b"\xff", b"[]", b'{"allowed":true}'):
            with self.subTest(data=data[:20]):
                result = self.evaluate(data)
                self.assertEqual(result.returncode, 3)
                self.assertIn("INVALID_DESCRIPTOR", json.loads(result.stdout)["reason_codes"])
                self.assertNotIn(b"private-marker", result.stdout + result.stderr)
                self.assertEqual(result.stderr, b"")

    def test_unknown_identifiers_are_not_echoed_and_invalid_policy_request_fails(self):
        result = self.run_cli(
            "--synthetic-only",
            "evaluate",
            "--case-key",
            "batch-synthetic-csv-1",
            "--actor",
            "private-marker",
            "--action",
            "approve",
            "--descriptor-stdin",
            data=self.receipt(),
        )
        self.assertEqual(result.returncode, 3)
        report = json.loads(result.stdout)
        self.assertEqual(report["context_status"], "VERIFIED")
        self.assertFalse(report["valid_combination"])
        self.assertNotIn(b"private-marker", result.stdout + result.stderr)

    def test_help_and_repeated_results_are_deterministic(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"DENY", result.stdout)
        receipt = self.receipt()
        self.assertEqual(self.evaluate(receipt).stdout, self.evaluate(receipt).stdout)
