import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from apps.editorial_export import services as exports
from apps.fast8_review_export import services as review


class CliTests(TestCase):
    def invoke(self, *args, opt_in=True, environment=None):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for key in ("FATWA_PRODUCTION", "DJANGO_SETTINGS_MODULE"):
            env.pop(key, None)
        env.update(environment or {})
        command = [sys.executable, "-B", "-m", "tools.fast9_prepared_review_lineage"]
        if opt_in:
            command.append("--synthetic-fixtures-only")
        return subprocess.run(command + list(args), capture_output=True, env=env, timeout=30)

    def test_stdout_is_exact_deterministic_utf8_record(self):
        first, second = self.invoke(), self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["status"], "SUPPORTED")
        self.assertIn("سُؤَالٌ".encode(), first.stdout)
        self.assertEqual(result["execution"]["postgresql"]["status"], "NOT_RUN")

    def test_default_off_and_production_guard(self):
        self.assertNotEqual(self.invoke(opt_in=False).returncode, 0)
        for env in (
            {"FATWA_PRODUCTION": "1"},
            {"DJANGO_SETTINGS_MODULE": "config.settings.production"},
        ):
            result = self.invoke(environment=env)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "REJECTED")

    def test_unknown_case_and_missing_draft(self):
        self.assertEqual(self.invoke("--case-key", "intake-7").returncode, 2)
        result = self.invoke("--case-key", "batch-synthetic-json-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertIsNone(record["prepared"]["final"]["record"])
        self.assertFalse(any(s["accepted"] for s in record["prepared"]["steps"]))

    def test_bundle_reads_preserve_bytes_and_modification_timestamps(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            source, preview = root / "source", root / "review"
            source.mkdir()
            preview.mkdir()
            files = dict(exports.build_export(synthetic_fixtures_only=True).files)
            projected = dict(review.build_preview(files, synthetic_fixtures_only=True).files)
            for directory, members in ((source, files), (preview, projected)):
                for name, raw in members.items():
                    (directory / name).write_bytes(raw)
            paths = list(source.iterdir()) + list(preview.iterdir())
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
            result = self.invoke("--source-bundle", str(source), "--review-bundle", str(preview))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})
            self.assertEqual(result.stdout, self.invoke().stdout)

    def test_altered_bundle_rejects_without_echoing_paths_or_source(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            files = dict(exports.build_export(synthetic_fixtures_only=True).files)
            for name, raw in files.items():
                (root / name).write_bytes(raw)
            marker = b"UNTRUSTED-CONTENT-MARKER"
            (root / "report.json").write_bytes(marker)
            result = self.invoke("--source-bundle", str(root))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "REJECTED")
            self.assertNotIn(marker, result.stdout + result.stderr)
            self.assertNotIn(str(root).encode(), result.stdout + result.stderr)
            self.assertEqual((root / "report.json").read_bytes(), marker)

    def test_missing_extra_directory_and_oversized_members_reject(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            files = dict(exports.build_export(synthetic_fixtures_only=True).files)
            for name, raw in files.items():
                (root / name).write_bytes(raw)
            member = root / "report.json"
            member.unlink()
            self.assertEqual(self.invoke("--source-bundle", str(root)).returncode, 2)
            member.mkdir()
            self.assertEqual(self.invoke("--source-bundle", str(root)).returncode, 2)
            member.rmdir()
            member.write_bytes(b"x" * (exports.MAX_FILE_BYTES + 1))
            self.assertEqual(self.invoke("--source-bundle", str(root)).returncode, 2)
            member.write_bytes(files["report.json"])
            (root / "extra.txt").write_bytes(b"synthetic-extra")
            self.assertEqual(self.invoke("--source-bundle", str(root)).returncode, 2)

    def test_review_bundle_requires_explicit_source_bundle(self):
        result = self.invoke("--review-bundle", "unread-synthetic-directory")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "REJECTED")
