"""Negative diagnostics at the directly affected legacy CLI boundary."""

import csv
import io
import json
import sys
from unittest import TestCase
from unittest.mock import patch

from tools.content_intake import cli


class LegacyDiagnosticTests(TestCase):
    def test_exception_messages_and_paths_cannot_escape_the_cli(self):
        marker = "SYNTHETIC-UNTRUSTED-DIAGNOSTIC"
        for exception, expected in (
            (ValueError(marker), "invalid input or bundle"),
            (OSError(2, marker, marker), "local file operation failed"),
            (csv.Error(marker), "invalid CSV input"),
            (UnicodeError(marker), "input contains invalid Unicode"),
            (json.JSONDecodeError(marker, marker, 2), "invalid JSON at line 1, column 3"),
        ):
            with self.subTest(exception=type(exception).__name__):
                output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                with (
                    patch.object(cli.Path, "open", side_effect=exception),
                    patch.object(sys, "stdout", output),
                ):
                    code = cli.main(["validate", marker + ".json"])
                    raw = output.buffer.getvalue()
                output.close()
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(raw), {"status": "INVALID", "error": expected})
                self.assertNotIn(marker.encode(), raw)

    def test_fixed_rejection_contracts_remain_actionable(self):
        for message in (
            "bundle differs from deterministic input-derived output",
            "bundle must be a new directory beneath the current working directory",
            "missing, duplicate or unknown CSV columns",
            "input: invalid_size_or_type",
            "duplicate JSON key",
        ):
            self.assertEqual(cli.safe_diagnostic(ValueError(message)), message)
