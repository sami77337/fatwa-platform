"""Mandatory browser gate: launch failure is FAIL, never an optional PASS/skip."""
import json
import os
import subprocess
from pathlib import Path

from .live_server import SyntheticLiveServerTestCase
from .support import require_disposable_database, seed_catalog

require_disposable_database()


class BrowserAcceptanceTests(SyntheticLiveServerTestCase):

    def test_desktop_and_mobile_journeys(self):
        seed_catalog()
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("browser.mjs")), self.live_server_url],
            env=os.environ.copy(), timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, "E6 browser gate failed/blocked; inspect browser-result.json. This is not browser acceptance.")
        artifacts = Path(os.environ.get(
            "E6_ARTIFACTS",
            str(Path(__file__).resolve().parents[3] / "docs/dev/e6/artifacts/latest"),
        ))
        report = json.loads((artifacts / "browser-result.json").read_text())
        startup = report["startup_observations"]
        self.assertEqual(startup["schema"], "fatwa.b6.startup-observations.v1")
        self.assertEqual(startup["result"], "READY")
        self.assertEqual(startup["root_cause"], "ROOT_CAUSE_UNKNOWN")
        self.assertEqual(startup["port_poll_limit_ms"], 12000)
        self.assertEqual(
            [row["phase"] for row in startup["phases"]],
            ["spawn", "port-file", "target-discovery", "websocket"],
        )
        self.assertGreaterEqual(startup["events"]["port-ready"]["count"], 1)
        self.assertEqual(startup["events"]["websocket-open"]["count"], 1)
