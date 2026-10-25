"""Real sandboxed Chrome checks against the guarded, database-free inspector."""

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from tests.acceptance.fastbuild.test_browser import editorial_server


class PermissionLabBrowserTests(SimpleTestCase):
    def test_connected_permission_form_keyboard_and_responsive_layout(self):
        with editorial_server() as origin:
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("browser.mjs")), origin],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
