"""Reuse the connected research browser with an explicit synthetic catalog; no DB."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench.services import _asserted_catalog
from apps.reference_links import SnapshotCatalog
from tests.acceptance.fastbuild.test_browser import editorial_server


class ConnectedJourneyBrowserTests(SimpleTestCase):
    def test_research_browser_startup_and_failure_contracts(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tools/dev/wave4_node.py"),
                str(root / "tests/research_bridge/startup.test.mjs"),
            ],
            env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_existing_research_triage_workbench_browser_journey(self):
        node = shutil.which("node")
        browser = os.environ.get("FATWA_FASTBUILD_BROWSER") or (
            "C:/Program Files/Google/Chrome/Application/chrome.exe"
            if os.name == "nt"
            else "/usr/bin/chromium"
        )
        if not node or not Path(browser).is_file():
            self.skipTest(
                "NOT_RUN: Node or Chrome/Chromium unavailable; no browser acceptance claimed"
            )
        catalog = SnapshotCatalog(_asserted_catalog())
        script = Path(__file__).resolve().parents[1] / "research_bridge" / "browser.mjs"
        with (
            patch(
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
                side_effect=catalog.lookup,
            ),
            editorial_server() as origin,
        ):
            result = subprocess.run(
                [node, str(script), origin],
                env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["catalog"], "fixed synthetic test double; no database")
        print(result.stdout.strip())
