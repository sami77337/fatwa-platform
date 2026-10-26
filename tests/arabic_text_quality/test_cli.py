"""Exercise the offline CLI against fabricated byte-exact local inputs."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class OfflineCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-arabic-quality-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def write(self, name, content):
        path = self.directory / name
        path.write_bytes(content)
        return path

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.arabic_text_quality", *map(str, arguments)],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
        )

    def test_utf8_bom_crlf_controls_and_astral_characters_are_preserved(self):
        text = "\ufeff\u0633\u0624\u0627\u0644 \U0001f4bb\r\n\u202eabc\u202c\t \r\n"
        content = text.encode("utf-8")
        source = self.write("fabricated-question.txt", content)
        first = self.invoke("--synthetic-only", "--input", source)
        second = self.invoke("--synthetic-only", "--input", source)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, b"")
        self.assertTrue(first.stdout.isascii())
        self.assertNotIn(b"\x1b", first.stdout)
        self.assertEqual(first.stdout.count(b"\n"), 1)
        self.assertTrue(first.stdout.endswith(b"\n"))
        self.assertNotIn(b"\r", first.stdout)
        report = json.loads(first.stdout)
        self.assertTrue(report["synthetic_only"])
        self.assertTrue(report["source_preserved"])
        self.assertEqual(report["sources"][0]["text"], text)
        self.assertEqual(report["sources"][0]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(source.read_bytes(), content)

    def test_before_and_after_have_independent_exact_source_identity(self):
        old = "\u0633\u0624\u0627\u0644\r\n\u0628 \u062c".encode("utf-8")
        new = "\u0633\u0624\u0627\u0644\n\u0628  \u062c".encode("utf-8")
        before = self.write("before.txt", old)
        after = self.write("after.txt", new)
        result = self.invoke(
            "--synthetic-only", "--input", after, "--before", before, "--kind", "revision"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        sources = {item["side"]: item for item in report["sources"]}
        self.assertEqual(sources["before"]["text"], old.decode("utf-8"))
        self.assertEqual(sources["after"]["text"], new.decode("utf-8"))
        self.assertEqual(before.read_bytes(), old)
        self.assertEqual(after.read_bytes(), new)
        self.assertTrue(report["diagnostics"])

    def test_inspection_accepts_empty_fabricated_text(self):
        source = self.write("empty.txt", b"")
        result = self.invoke("--synthetic-only", "--input", source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sources"][0]["text"], "")

    def test_explicit_synthetic_acknowledgement_is_required(self):
        source = self.write("synthetic.txt", b"synthetic")
        result = self.invoke("--input", source)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_invalid_utf8_fails_without_echoing_path_or_content(self):
        source = self.write("SYNTHETIC-PATH-MARKER.txt", b"SYNTHETIC-CONTENT-MARKER\xff")
        result = self.invoke("--synthetic-only", "--input", source)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"SYNTHETIC-PATH-MARKER", result.stderr)
        self.assertNotIn(b"SYNTHETIC-CONTENT-MARKER", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_missing_file_fails_without_echoing_path(self):
        result = self.invoke(
            "--synthetic-only", "--input", self.directory / "SYNTHETIC-MISSING-MARKER.txt"
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"SYNTHETIC-MISSING-MARKER", result.stderr)

    def test_directory_input_is_rejected(self):
        result = self.invoke("--synthetic-only", "--input", self.directory)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_codepoint_limit_is_not_a_utf8_byte_limit(self):
        source = self.write("astral-bound.txt", ("\U0001f4bb" * 10000).encode("utf-8"))
        result = self.invoke("--synthetic-only", "--input", source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sources"][0]["codepoint_length"], 10000)

    def test_oversized_inputs_are_rejected(self):
        for name, content in (
            ("too-many-codepoints.txt", b"x" * 10001),
            ("too-many-bytes.txt", b"x" * 40001),
        ):
            with self.subTest(name=name):
                source = self.write(name, content)
                result = self.invoke("--synthetic-only", "--input", source)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")

    def test_fail_on_threshold_changes_exit_status_without_suppressing_report(self):
        source = self.write("control.txt", b"x\x00y")
        default = self.invoke("--synthetic-only", "--input", source)
        threshold = self.invoke("--synthetic-only", "--input", source, "--fail-on", "info")
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(threshold.returncode, 1, threshold.stderr)
        self.assertEqual(json.loads(default.stdout), json.loads(threshold.stdout))
        clean = self.write("clean.txt", b"Synthetic question")
        result = self.invoke("--synthetic-only", "--input", clean, "--fail-on", "error")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_before_does_not_emit_partial_after_report(self):
        before = self.write("bad-before.txt", b"\xff")
        after = self.write("after.txt", b"Synthetic revision")
        result = self.invoke("--synthetic-only", "--input", after, "--before", before)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_help_runs_without_source_files(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--synthetic-only", result.stdout)
        self.assertIn(b"--before", result.stdout)

    def test_network_device_and_drive_relative_paths_are_rejected(self):
        for path in (
            r"\\synthetic.invalid\share\question.txt",
            "//synthetic.invalid/share/a",
            r"\\.\NUL",
            "NUL",
            "C:synthetic.txt",
        ):
            with self.subTest(path=path):
                result = self.invoke("--synthetic-only", "--input", path)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr.strip(), b"INPUT_INVALID")

    def test_unknown_argument_is_not_echoed_to_stderr(self):
        source = self.write("question.txt", b"Synthetic question")
        result = self.invoke("--synthetic-only", "--input", source, "--SYNTHETIC-ARGUMENT-MARKER")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"SYNTHETIC-ARGUMENT-MARKER", result.stderr)
