"""Execute the synthetic journey without file inputs or persisted outputs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[2]


class JourneyCliTests(TestCase):
    def invoke(self, *arguments, production="0"):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DJANGO_SETTINGS_MODULE", "FATWA_PRODUCTION"}
        }
        environment["FATWA_PRODUCTION"] = production
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast6_journey", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=60,
        )

    def test_stdout_is_deterministic_canonical_utf8_json(self):
        first = self.invoke("--synthetic-fixtures-only")
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8"))
        self.assertEqual(first.stderr, b"")
        payload = json.loads(first.stdout.decode("utf-8"))
        self.assertIsInstance(payload, dict)
        self.assertEqual(
            first.stdout,
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8"),
        )
        second = self.invoke("--synthetic-fixtures-only")
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8"))
        self.assertEqual(first.stdout, second.stdout)
        from apps.fast6_journey.services import run_journey

        self.assertEqual(first.stdout, run_journey(synthetic_fixtures_only=True).json_bytes)

    def test_acknowledgement_is_required(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)

    def test_arbitrary_inputs_and_outputs_are_rejected_without_echo(self):
        for option in ("--input", "--output", "--synthetic-fixtures"):
            with self.subTest(option=option):
                result = self.invoke("--synthetic-fixtures-only", option, "private-fixture-value")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"private-fixture-value", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_production_refusal_returns_no_report(self):
        result = self.invoke("--synthetic-fixtures-only", production="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
