"""Real browser UI over explicit synthetic catalog test double; no database."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench.services import _asserted_catalog
from apps.reference_links import SnapshotCatalog
from tests.acceptance.fastbuild.test_browser import editorial_server


class ResearchBrowserTests(SimpleTestCase):
    def test_keyboard_mobile_and_exact_text_with_synthetic_catalog(self):
        catalog = SnapshotCatalog(_asserted_catalog())
        with (
            patch(
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
                side_effect=catalog.lookup,
            ),
            editorial_server() as origin,
        ):
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("browser.mjs")), origin],
                env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
