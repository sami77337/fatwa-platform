"""Comparison CLI reads bounded bundles and only creates a new result file."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.__main__ import main
from apps.editorial_export.services import ExportError, build_export


class ComparisonCliTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before, self.after = self.root / "before", self.root / "after"
        self.output = self.root / "comparison.json"
        self.files = dict(build_export(synthetic_fixtures_only=True).files)
        for directory in (self.before, self.after):
            directory.mkdir()
            for name, raw in self.files.items():
                (directory / name).write_bytes(raw)

    def arguments(self, output=None):
        return [
            "compare",
            "--synthetic-fixtures-only",
            "--before",
            str(self.before),
            "--after",
            str(self.after),
            "--output",
            str(self.output if output is None else output),
        ]

    def invoke(self, output=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(self.arguments(output))
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_inputs_unchanged(self):
        for directory in (self.before, self.after):
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, self.files)

    def test_comparison_creates_deterministic_report_without_touching_inputs(self):
        self.assertEqual(self.invoke()[0], 0)
        raw = self.output.read_bytes()
        self.assertTrue(json.loads(raw)["identical"])
        another = self.root / "another.json"
        self.assertEqual(self.invoke(another)[0], 0)
        self.assertEqual(raw, another.read_bytes())
        self.assert_inputs_unchanged()

    def test_existing_output_and_output_inside_either_bundle_are_rejected(self):
        self.output.write_bytes(b"keep this synthetic output")
        self.assertEqual(self.invoke()[0], 1)
        self.assertEqual(self.output.read_bytes(), b"keep this synthetic output")
        for directory in (self.before, self.after):
            for filename in ("comparison.json", "report.json"):
                self.assertEqual(self.invoke(directory / filename)[0], 1)
        self.assert_inputs_unchanged()

    def test_tampered_second_input_fails_without_partial_output_or_source_echo(self):
        (self.after / "report.json").write_bytes(b"SYNTHETIC-DO-NOT-ECHO")
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn("SYNTHETIC-DO-NOT-ECHO", stderr)
        self.assertNotIn(str(self.after), stderr)
        self.assertFalse(self.output.exists())

    def test_missing_extra_and_non_regular_files_are_rejected(self):
        (self.after / "report.json").unlink()
        self.assertEqual(self.invoke()[0], 1)
        (self.after / "report.json").mkdir()
        self.assertEqual(self.invoke()[0], 1)
        (self.after / "report.json").rmdir()
        (self.after / "report.json").write_bytes(self.files["report.json"])
        (self.after / "extra.txt").write_bytes(b"synthetic extra")
        self.assertEqual(self.invoke()[0], 1)
        self.assertFalse(self.output.exists())

    def test_bounds_and_symlink_checks_are_reused_before_comparison(self):
        with patch("apps.editorial_export.__main__.compare_exports") as compare:
            with patch("apps.editorial_export.services.MAX_FILE_BYTES", 1):
                self.assertEqual(self.invoke()[0], 1)
            with patch("apps.editorial_export.__main__._regular_file", return_value=False):
                self.assertEqual(self.invoke()[0], 1)
            compare.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_guard_and_missing_opt_in_precede_reads_and_output(self):
        with patch("apps.editorial_export.__main__.read_bundle") as read:
            with patch.dict(os.environ, FATWA_PRODUCTION="1"):
                self.assertEqual(self.invoke()[0], 1)
            args = self.arguments()
            args.remove("--synthetic-fixtures-only")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)
            read.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_inputs_unchanged()

    def test_output_bound_failure_creates_no_partial_report(self):
        with patch(
            "apps.editorial_export.__main__.compare_exports", side_effect=ExportError("bounds")
        ):
            self.assertEqual(self.invoke()[0], 1)
        self.assertFalse(self.output.exists())
        self.assert_inputs_unchanged()

    def test_executable_cli_without_django_setup(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DJANGO_SETTINGS_MODULE", "FATWA_PRODUCTION"}
        }
        result = subprocess.run(
            [sys.executable, "-m", "apps.editorial_export", *self.arguments()],
            env=env,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"COMPARED", result.stdout)
        self.assertTrue(json.loads(self.output.read_bytes())["identical"])
        self.assert_inputs_unchanged()
