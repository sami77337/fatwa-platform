"""Exercise the offline CLI boundary with fabricated local files only."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.source_readiness.fixtures import bundle, encode

ROOT = Path(__file__).resolve().parents[2]


class SourceReadinessCLITests(unittest.TestCase):
    def write_bundle(self, directory, source_kind="synthetic"):
        manifest, snapshot, raw, archive = bundle()
        manifest["source_kind"] = source_kind
        files = {
            "manifest": encode(manifest),
            "snapshot": encode(snapshot),
            "input": raw,
            "archive": archive,
        }
        paths = {}
        for name, content in files.items():
            paths[name] = Path(directory) / name
            paths[name].write_bytes(content)
        return paths

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tools.source_readiness", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def report(self, result, status, exit_code):
        self.assertEqual(result.returncode, exit_code, result.stderr.decode(errors="replace"))
        self.assertEqual(result.stderr, b"")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], status)
        self.assertEqual(
            result.stdout,
            (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii"),
        )
        return payload

    def test_no_arguments_returns_not_run_json_deterministically(self):
        first = self.run_cli()
        self.report(first, "NOT_RUN", 3)
        self.assertEqual(first.stdout, self.run_cli().stdout)

    def test_invalid_arguments_are_json_without_echoing_values(self):
        for args in (("--private-option", "private-text"), ("--manifest",)):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.report(result, "BLOCKED", 2)
                self.assertIn(b"CLI_ARGUMENTS_INVALID", result.stdout)
                self.assertNotIn(b"private", result.stdout)

    def test_missing_manifest_is_blocked_without_path_or_trace(self):
        result = self.run_cli("--manifest", "private-missing-manifest.json")
        self.report(result, "BLOCKED", 2)
        self.assertIn(b"MANIFEST_UNREADABLE", result.stdout)
        self.assertNotIn(b"private-missing", result.stdout)
        self.assertNotIn(b"Traceback", result.stdout)

    def test_directory_and_oversized_manifest_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("--manifest", directory)
            self.report(result, "BLOCKED", 2)
            self.assertIn(b"MANIFEST_NOT_REGULAR", result.stdout)
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (64 * 1024 + 1))
            result = self.run_cli("--manifest", path)
            self.report(result, "BLOCKED", 2)
            self.assertIn(b"MANIFEST_TOO_LARGE", result.stdout)

    def test_remote_device_and_drive_relative_paths_are_rejected(self):
        for path in (
            r"\\private-server\share\input.json",
            "//private/input.json",
            r"\\?\C:\private.json",
            r"\\.\NUL",
            "C:private.json",
            "NUL.json",
        ):
            with self.subTest(path=path):
                result = self.run_cli("--manifest", path)
                self.report(result, "BLOCKED", 2)
                self.assertIn(b"MANIFEST_NOT_REGULAR", result.stdout)
                self.assertNotIn(b"private", result.stdout)

    def test_malformed_manifest_fails_before_other_paths_are_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(b'{"private-value":')
            result = self.run_cli(
                "--manifest",
                path,
                "--snapshot",
                "private-missing-snapshot.json",
                "--input",
                "private-missing-input.json",
                "--archive",
                "private-missing.zip",
            )
            self.report(result, "FAIL", 1)
            self.assertNotIn(b"UNREADABLE", result.stdout)
            self.assertNotIn(b"private", result.stdout)

    def test_no_manifest_does_not_read_supplied_paths(self):
        result = self.run_cli("--input", "private-missing.json", "--archive", "private.zip")
        self.report(result, "NOT_RUN", 3)
        self.assertNotIn(b"UNREADABLE", result.stdout)

    def test_pinned_owner_reports_blocked_without_opening_raw_paths(self):
        result = self.run_cli(
            "--pinned-owner", "--input", "private-missing.json", "--archive", "private.zip"
        )
        report = self.report(result, "BLOCKED", 2)
        self.assertEqual(report["owner_acceptance"], "NOT_RUN")
        self.assertEqual(report["observed_sha256"], {})
        self.assertNotIn(b"UNREADABLE", result.stdout)
        self.assertNotIn(b"CLI_ARGUMENTS_INVALID", result.stdout)

    def test_pinned_owner_and_manifest_are_mutually_exclusive(self):
        result = self.run_cli("--pinned-owner", "--manifest", "private-missing.json")
        self.report(result, "BLOCKED", 2)
        self.assertIn(b"CLI_ARGUMENTS_INVALID", result.stdout)
        self.assertNotIn(b"private-missing", result.stdout)

    def test_unavailable_inherited_metadata_has_fixed_failure_diagnostic(self):
        from tools.source_readiness.cli import main

        for error in (OSError("private-path"), ValueError("private-metadata")):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch("apps.source_readiness.pins.pinned_owner_manifest", side_effect=error):
                    with redirect_stdout(output):
                        code = main(["--pinned-owner"])
                self.assertEqual(code, 1)
                report = json.loads(output.getvalue())
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("INHERITED_OWNER_METADATA_INVALID", output.getvalue())
                self.assertNotIn("private", output.getvalue())

    def test_synthetic_bundle_passes_without_modifying_any_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_bundle(directory)
            before = {name: path.read_bytes() for name, path in paths.items()}
            args = [arg for name, path in paths.items() for arg in ("--" + name, path)]
            result = self.run_cli(*args)
            report = self.report(result, "PASS", 0)
            self.assertEqual(report["owner_acceptance"], "NOT_RUN")
            self.assertEqual(result.stdout, self.run_cli(*args).stdout)
            self.assertEqual(before, {name: path.read_bytes() for name, path in paths.items()})
            self.assertEqual(set(Path(directory).iterdir()), set(paths.values()))

    def test_synthetic_missing_or_oversized_raw_files_block(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_bundle(directory)
            for label in ("snapshot", "input", "archive"):
                with self.subTest(label=label):
                    args = ("--manifest", paths["manifest"], "--" + label)
                    result = self.run_cli(*args, Path(directory) / "private-missing")
                    self.report(result, "BLOCKED", 2)
                    self.assertIn((label.upper() + "_UNREADABLE").encode(), result.stdout)
                    self.assertNotIn(b"private-missing", result.stdout)
                    oversized = Path(directory) / "oversized"
                    with oversized.open("wb") as stream:
                        stream.truncate(16 * 1024 * 1024 + 1)
                    result = self.run_cli(*args, oversized)
                    self.report(result, "BLOCKED", 2)
                    self.assertIn((label.upper() + "_TOO_LARGE").encode(), result.stdout)

    def test_owner_manifest_never_opens_raw_input_or_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_bundle(directory, source_kind="owner_supplied")
            program = (
                "import os, runpy, sys\n"
                "forbidden = {os.path.abspath(sys.argv[-3]), os.path.abspath(sys.argv[-1])}\n"
                "def audit(event, args):\n"
                "    if event == 'open' and isinstance(args[0], str):\n"
                "        if os.path.abspath(args[0]) in forbidden:\n"
                "            raise AssertionError('raw file was opened')\n"
                "sys.addaudithook(audit)\n"
                "sys.argv[0] = 'tools.source_readiness'\n"
                "runpy.run_module('tools.source_readiness', run_name='__main__')\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    program,
                    "--manifest",
                    str(paths["manifest"]),
                    "--snapshot",
                    str(paths["snapshot"]),
                    "--input",
                    str(paths["input"]),
                    "--archive",
                    str(paths["archive"]),
                ],
                cwd=ROOT,
                capture_output=True,
                timeout=15,
                check=False,
            )
            report = self.report(result, "BLOCKED", 2)
            self.assertEqual(report["owner_acceptance"], "NOT_RUN")
            self.assertEqual(report["observed_sha256"], {})

    def test_symbolic_link_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_bytes(b"{}")
            link = Path(directory) / "link.json"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(
                    f"Symlink creation unavailable: {getattr(error, 'winerror', error.errno)}"
                )
            result = self.run_cli("--manifest", link)
            self.report(result, "BLOCKED", 2)
            self.assertIn(b"MANIFEST_NOT_REGULAR", result.stdout)


if __name__ == "__main__":
    unittest.main()
