"""Integrated Chrome navigation; matching uses an explicit synthetic catalog double."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench.services import _asserted_catalog
from apps.reference_links import SnapshotCatalog
from tests.acceptance.fastbuild.test_browser import editorial_server


class Fast5BrowserTests(SimpleTestCase):
    def test_connected_fast5_and_fast4_pages(self):
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
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
