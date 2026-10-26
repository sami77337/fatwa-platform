"""Offline CLI contract: fixed synthetic input, deterministic UTF-8, fail closed."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from tools.fiqh_reading_trail.fixtures import FIXTURE_ID, fixture_sha256

ROOT = Path(__file__).resolve().parents[2]


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-B", "-m", "tools.fiqh_reading_trail", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=20,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


class CliTests(TestCase):
    def test_explicit_synthetic_acknowledgment_required(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_deterministic_utf8_report_with_real_fixture_digest(self):
        first = run_cli("--synthetic-fixtures-only")
        second = run_cli("--synthetic-fixtures-only")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, b"")
        report = json.loads(first.stdout.decode("utf-8"))
        self.assertEqual(report["schema"], "fatwa.fiqh-reading-trail.v1")
        self.assertEqual(report["fixture_id"], FIXTURE_ID)
        self.assertEqual(report["fixture_sha256"], fixture_sha256())
        self.assertTrue(report["synthetic_only"])
        self.assertEqual(report["gates"]["B"], "NOT_PASSED")
        self.assertEqual(report["gates"]["Phase01"], "BLOCKED")
        self.assertEqual(report["trail"]["current"]["evidence"]["source_row_id"], 40)
        self.assertIn("فَصْلٌ", first.stdout.decode("utf-8"))

    def test_reference_entry_returns_to_exact_original_occurrence(self):
        result = run_cli("--synthetic-fixtures-only", "--from-reference", "--source-row-id", "42")
        self.assertEqual(result.returncode, 0, result.stderr)
        trail = json.loads(result.stdout)["trail"]
        self.assertEqual(trail["research_return_url"], "/dev/research-bridge/intake-1#reference-1")
        self.assertEqual(len(trail["breadcrumbs"]), 5)

    def test_unknown_heading_reports_closed_result_without_links(self):
        result = run_cli("--synthetic-fixtures-only", "--source-row-id", "999")
        self.assertEqual(result.returncode, 2)
        trail = json.loads(result.stdout)["trail"]
        self.assertEqual(trail["status"], "unverified")
        for key in ("current", "previous", "next", "catalog_return_url", "research_return_url"):
            self.assertIsNone(trail[key])
        self.assertEqual(trail["breadcrumbs"], [])

    def test_cli_rejects_inputs_network_paths_overrides_and_abbreviations(self):
        for arguments in (
            ("--input", "PRIVATE-SENTINEL.json"),
            ("--source-row-id", "PRIVATE-SENTINEL"),
            ("--source-row-id", "١"),
            ("--source-row-id", "0"),
            ("--source-row-id", str(2**63)),
            ("--source-row-id", "1e2"),
            ("--edition", "7002"),
            ("--return-url", "https://PRIVATE-SENTINEL"),
            ("--output", "PRIVATE-SENTINEL.json"),
            ("--synthetic-fixtures-onl",),
        ):
            with self.subTest(arguments=arguments):
                result = run_cli("--synthetic-fixtures-only", *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"PRIVATE-SENTINEL", result.stderr)
