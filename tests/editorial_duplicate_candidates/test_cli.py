"""Exercise the real offline entry point without Django setup or database IO."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.editorial_duplicate_candidates.cli import main

ROOT = Path(__file__).resolve().parents[2]


class DuplicateCLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        environment = dict(os.environ)
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.editorial_duplicate_candidates", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_real_cli_emits_stable_utf8_json(self):
        first = self.run_cli("--synthetic-fixtures-only")
        second = self.run_cli("--synthetic-fixtures-only")
        self.assertEqual(first.returncode, 0, first.stderr.decode())
        self.assertEqual(second.returncode, 0, second.stderr.decode())
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.endswith(b"\n"))
        report = json.loads(first.stdout.decode("utf-8"))
        self.assertIs(report["synthetic_only"], True)
        self.assertIn("سؤال", first.stdout.decode("utf-8"))

    def test_requires_full_acknowledgement_and_rejects_external_inputs_without_echo(self):
        for arguments in (
            (),
            ("--synthetic",),
            ("--synthetic-fixtures-only", "--input", "PRIVATE-PATH"),
            ("--synthetic-fixtures-only", "PRIVATE-CONTENT"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"PRIVATE", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_expected_service_failure_is_redacted_and_emits_no_report(self):
        from apps.editorial_duplicate_candidates.services import DuplicateCandidateError

        output, errors = io.StringIO(), io.StringIO()
        with (
            patch(
                "apps.editorial_duplicate_candidates.services.build_duplicate_report",
                side_effect=DuplicateCandidateError("PRIVATE-SOURCE"),
            ),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(main(["--synthetic-fixtures-only"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("PRIVATE-SOURCE", errors.getvalue())

    def test_parser_rejects_before_service_runs(self):
        with (
            patch("apps.editorial_duplicate_candidates.services.build_duplicate_report") as build,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as caught,
        ):
            main([])
        self.assertEqual(caught.exception.code, 2)
        build.assert_not_called()
