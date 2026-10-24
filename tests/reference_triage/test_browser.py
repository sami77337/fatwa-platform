"""Focused real-browser investigation checks; never opens a database."""

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from tests.acceptance.fastbuild.test_browser import editorial_server


class InvestigationBrowserTests(SimpleTestCase):
    def test_investigation_mobile_navigation_and_exact_text(self):
        with editorial_server() as origin:
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("browser.mjs")), origin],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
