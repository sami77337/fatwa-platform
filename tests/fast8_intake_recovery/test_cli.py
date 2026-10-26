"""Observable stdout, exit codes and path rejection via the real module entrypoint."""

import json
import subprocess
import sys
import unittest


def run(*arguments):
    return subprocess.run(
        [sys.executable, "-B", "-m", "tools.fast8_intake_recovery", *arguments],
        capture_output=True,
        timeout=20,
        check=False,
    )


class CLITests(unittest.TestCase):
    def test_full_preview_has_real_failures_and_deterministic_utf8_json(self):
        first = run("--json")
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertEqual(first.stderr, b"")
        report = json.loads(first.stdout)
        self.assertEqual(report["summary"]["selected_failed_rows"], 6)
        self.assertEqual(report["accepted_record_count"], 0)
        self.assertIn("سُؤَالٌ".encode(), first.stdout)
        self.assertEqual(run("--json").stdout, first.stdout)

    def test_selected_original_row_and_review_only_exit(self):
        selected = run("--batch", "synthetic-jsonl", "--row", "1", "--json")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)["rows"][0]["state"], "MANUAL_REVIEW_REQUIRED")
        failed = run("--batch", "synthetic-csv", "--row", "4", "--json")
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["rows"][0]["row"], 4)

    def test_arabic_malformed_preview_and_failed_filter(self):
        result = run("--batch", "synthetic-malformed")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("تعذر تحديد الصفوف", result.stdout.decode("utf-8"))
        self.assertIn(b"MALFORMED_INPUT", result.stdout)
        failed = run("--failed-only", "--json")
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(len(json.loads(failed.stdout)["rows"]), 6)

    def test_invalid_selection_paths_input_output_and_write_options_are_rejected(self):
        for arguments in (
            ("--batch", "../../private.json"),
            ("--batch", "C:\\private\\input.csv"),
            ("--batch", "https://example.invalid/data"),
            ("--row", "1"),
            ("--batch", "synthetic-csv", "--row", "0"),
            ("--batch", "synthetic-malformed", "--row", "1"),
            ("--batch", "synthetic-csv", "--row", "1", "--failed-only"),
            ("--input", "private.json"),
            ("--output", "private.json"),
            ("--resubmit",),
            ("--source-id", "W7-SOURCE"),
            ("private.json",),
        ):
            with self.subTest(arguments=arguments):
                result = run(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)
