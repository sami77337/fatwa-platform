"""Mandatory browser gate: launch failure is FAIL, never an optional PASS/skip."""
import os
from pathlib import Path
import subprocess

from django.test import LiveServerTestCase

from .support import require_disposable_database, seed_catalog

require_disposable_database()


class BrowserAcceptanceTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_desktop_and_mobile_journeys(self):
        seed_catalog()
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("browser.mjs")), self.live_server_url],
            env=os.environ.copy(), timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, "E6 browser gate failed/blocked; inspect browser-result.json. This is not browser acceptance.")
