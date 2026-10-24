"""Executable failure paths must retain NOT_RUN cases and nonzero exit codes."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from .test_browser import editorial_server, run_browser


class RunnerFailureTests(SimpleTestCase):
    def test_catalog_without_lane_opt_in_reports_every_case_not_run(self):
        with tempfile.TemporaryDirectory(prefix="fatwa-fastbuild-report-") as directory:
            environment = {
                **os.environ,
                "FATWA_WAVE7_E6_ACCEPTANCE": "0",
                "FATWA_FASTBUILD_ARTIFACTS": directory,
            }
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("run.py")), "--catalog"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(Path(directory, "catalog-result.json").read_text())
            self.assertEqual(report["result"], "NOT_RUN")
            self.assertEqual(report["blocker"], "E6_ACCEPTANCE_OPT_IN_REQUIRED")
            self.assertEqual(report["counts"], {"PASS": 0, "FAIL": 0, "NOT_RUN": 5})
            self.assertEqual(report["requests"], [])

    def test_missing_browser_never_reports_editorial_acceptance_pass(self):
        with tempfile.TemporaryDirectory(prefix="fatwa-fastbuild-report-") as directory:
            with (
                patch.dict(
                    os.environ,
                    {
                        "FATWA_FASTBUILD_ARTIFACTS": directory,
                        "FATWA_FASTBUILD_BROWSER": str(Path(directory, "missing-browser")),
                    },
                ),
                editorial_server() as origin,
            ):
                result = run_browser(origin, "editorial")
            self.assertEqual(result, 2)
            report = json.loads(Path(directory, "editorial-result.json").read_text())
            self.assertEqual(report["result"], "NOT_RUN")
            self.assertEqual(report["phase"], "browser-startup")
            self.assertEqual(report["counts"], {"PASS": 0, "FAIL": 0, "NOT_RUN": 14})
            self.assertEqual(report["requests"], [])
