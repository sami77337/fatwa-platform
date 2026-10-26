import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.editorial_queue.services import build_queue_catalog
from apps.reference_links.resolution import CatalogReadError
from tests.acceptance.fastbuild.test_browser import editorial_server


@override_settings(ROOT_URLCONF="tests.fast8_operator_nav.urls")
class OperatorBrowserTests(SimpleTestCase):
    def test_guarded_operator_journey(self):
        exact = next(
            row.case for row in build_queue_catalog().rows if "\r" in (row.case.question or "")
        )
        expected = json.dumps({"key": exact.key, "question": exact.question})
        # Explicit unavailable-catalog double. No source archive or DB acceptance.
        with (
            patch(
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
                side_effect=CatalogReadError("synthetic unavailable catalog"),
            ),
            editorial_server() as origin,
        ):
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("browser.mjs")), origin, expected],
                env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
