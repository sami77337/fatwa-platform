"""Executable previews never modify a preexisting immutable export directory."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from apps.editorial_export.services import build_export


class PreviewCliTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.original = dict(build_export(synthetic_fixtures_only=True).files)
        for name, raw in self.original.items():
            (self.source / name).write_bytes(raw)
        self.output = self.root / "preview"

    def invoke(self, command, *arguments, environment=None, opt_in=True):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DJANGO_SETTINGS_MODULE", "FATWA_PRODUCTION"}
        }
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(environment or {})
        invocation = [sys.executable, "-B", "-m", "tools.fast8_review_export", command]
        if opt_in:
            invocation.append("--synthetic-fixtures-only")
        invocation.extend(["--source-bundle", str(self.source), *arguments])
        return subprocess.run(invocation, capture_output=True, timeout=30, env=env)

    def current_source(self):
        return {path.name: path.read_bytes() for path in self.source.iterdir()}

    def test_cli_preview_and_verify_preserve_source_files_and_timestamps(self):
        before_times = {path.name: path.stat().st_mtime_ns for path in self.source.iterdir()}
        created = self.invoke("preview", "--output", str(self.output))
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn(b"NOT_DEPLOYED", created.stdout)
        self.assertEqual(
            set(path.name for path in self.output.iterdir()),
            {"preview.json", "review-events.csv", "manifest.json"},
        )
        verified = self.invoke("verify", "--input", str(self.output))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(self.current_source(), self.original)
        self.assertEqual(
            {path.name: path.stat().st_mtime_ns for path in self.source.iterdir()}, before_times
        )

    def test_cli_rejects_existing_output_without_overwriting_any_bytes(self):
        self.assertEqual(self.invoke("preview", "--output", str(self.output)).returncode, 0)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        repeated = self.invoke("preview", "--output", str(self.output))
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, before)
        self.assertEqual(self.current_source(), self.original)

    def test_cli_rejects_output_inside_source_before_creating_a_directory(self):
        for target in (self.source, self.source / "preview"):
            with self.subTest(target=target.name):
                result = self.invoke("preview", "--output", str(target))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.current_source(), self.original)

    def test_cli_default_off_and_production_guard_create_nothing(self):
        missing_flag = self.invoke("preview", "--output", str(self.output), opt_in=False)
        self.assertNotEqual(missing_flag.returncode, 0)
        self.assertFalse(self.output.exists())
        production = self.invoke(
            "preview", "--output", str(self.output), environment={"FATWA_PRODUCTION": "1"}
        )
        self.assertNotEqual(production.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.current_source(), self.original)

    def test_cli_rejects_tampered_input_without_creating_preview_or_echoing_content(self):
        marker = b"SYNTHETIC-ERROR-CONTENT-MUST-NOT-BE-ECHOED"
        (self.source / "report.json").write_bytes(marker)
        result = self.invoke("preview", "--output", str(self.output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn(str(self.source).encode(), result.stdout + result.stderr)

    def test_cli_verify_rejects_altered_or_extra_preview_files(self):
        self.assertEqual(self.invoke("preview", "--output", str(self.output)).returncode, 0)
        path = self.output / "preview.json"
        before = path.read_bytes()
        path.write_bytes(before + b"\n")
        self.assertNotEqual(self.invoke("verify", "--input", str(self.output)).returncode, 0)
        path.write_bytes(before)
        (self.output / "extra.txt").write_bytes(b"synthetic-extra")
        self.assertNotEqual(self.invoke("verify", "--input", str(self.output)).returncode, 0)
        self.assertEqual(self.current_source(), self.original)

    def test_cli_rejects_directory_in_place_of_regular_source_file(self):
        path = self.source / "cases.csv"
        path.unlink()
        path.mkdir()
        result = self.invoke("preview", "--output", str(self.output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_cli_rejects_oversized_source_without_creating_preview(self):
        from apps.editorial_export.services import MAX_FILE_BYTES

        (self.source / "cases.csv").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        result = self.invoke("preview", "--output", str(self.output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_cli_verify_rejects_the_wrong_fixed_scenario(self):
        created = self.invoke("preview", "--scenario", "blocked", "--output", str(self.output))
        self.assertEqual(created.returncode, 0, created.stderr)
        verified = self.invoke("verify", "--scenario", "blocked", "--input", str(self.output))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertNotEqual(
            self.invoke(
                "verify", "--scenario", "rehearsal", "--input", str(self.output)
            ).returncode,
            0,
        )
