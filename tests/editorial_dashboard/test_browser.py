"""Focused dashboard browser checks over the real guarded Django application."""

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from tests.acceptance.fastbuild.test_browser import editorial_server


class DashboardBrowserTests(SimpleTestCase):
    def test_dashboard_responsive_navigation_and_exact_arabic(self):
        # The existing WSGI harness and SimpleTestCase forbid database access.
        with editorial_server() as origin:
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("browser.mjs")), origin],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
