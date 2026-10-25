"""Offline command, exclusive outputs and bounded replay input."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class ExportCliTests(TestCase):
    def invoke(self, *arguments):
        from apps.editorial_export.__main__ import main

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(list(arguments))

    def test_export_verify_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            self.assertEqual(
                self.invoke("export", "--synthetic-fixtures-only", "--output", str(output)), 0
            )
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertEqual(
                set(before), {"report.json", "cases.csv", "batches.csv", "manifest.json"}
            )
            self.assertEqual(
                self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 0
            )
            self.assertEqual(
                self.invoke("export", "--synthetic-fixtures-only", "--output", str(output)), 1
            )
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
            (output / "cases.csv").write_bytes(before["cases.csv"] + b"\n")
            self.assertEqual(
                self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 1
            )

    def test_no_side_effects_on_guard_failure_or_invalid_export(self):
        from apps.editorial_export.services import ExportError

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                self.assertEqual(
                    self.invoke("export", "--synthetic-fixtures-only", "--output", str(output)), 1
                )
            self.assertFalse(output.exists())
            with patch(
                "apps.editorial_export.__main__.build_export", side_effect=ExportError("bad")
            ):
                self.assertEqual(
                    self.invoke("export", "--synthetic-fixtures-only", "--output", str(output)), 1
                )
            self.assertFalse(output.exists())
            with self.assertRaises(SystemExit) as error:
                self.invoke("export", "--output", str(output))
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(output.exists())

    def test_verify_rejects_missing_extra_directory_and_oversized_files(self):
        from apps.editorial_export import services

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            self.assertEqual(
                self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 1
            )
            self.invoke("export", "--synthetic-fixtures-only", "--output", str(output))
            (output / "extra").write_bytes(b"extra")
            self.assertEqual(
                self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 1
            )
            (output / "extra").unlink()
            with patch.object(services, "MAX_FILE_BYTES", 20):
                self.assertEqual(
                    self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 1
                )
            (output / "cases.csv").unlink()
            (output / "cases.csv").mkdir()
            self.assertEqual(
                self.invoke("verify", "--synthetic-fixtures-only", "--input", str(output)), 1
            )

    def test_executable_cli_needs_no_django_setup_or_network(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DJANGO_SETTINGS_MODULE", "FATWA_PRODUCTION"}
        }
        with tempfile.TemporaryDirectory() as tmp:
            command = [
                sys.executable,
                "-m",
                "apps.editorial_export",
                "export",
                "--synthetic-fixtures-only",
                "--output",
                str(Path(tmp) / "bundle"),
            ]
            result = subprocess.run(command, env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"NOT_DEPLOYED", result.stdout)
