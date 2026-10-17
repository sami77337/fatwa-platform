"""Separate baseline vs mandatory persisted browser gates; never optional PASS."""
import json
import os
from pathlib import Path
import subprocess

from apps.intake_workflow import fixtures as f, guards as g
from .test_assets import E6LiveServer
from .target import require_lane_configuration

require_lane_configuration()


class BrowserBaselineTests(E6LiveServer):
    def test_protected_engine_catalog_desktop_and_mobile(self):
        g.require_synthetic_write(synthetic_fixtures_only=True)
        f.seed_reference_catalog(synthetic_fixtures_only=True)  # outside any outer atomic
        result = subprocess.run(["node", str(Path(__file__).with_name("browser.mjs")),
            self.live_server_url], check=False, timeout=180)
        self.assertEqual(result.returncode, 0, "Baseline browser BLOCKED/FAIL; read browser-result.json. Persisted workflow not implied.")


class PersistedWorkflowBrowserTests(E6LiveServer):
    def test_actual_persisted_multibatch_workflow(self):
        from .workflow_contract import prepare_workflow_scenario, WorkflowIntegrationPending
        g.require_synthetic_write(synthetic_fixtures_only=True)
        artifacts = Path(os.environ.get("E6_WAVE7_ARTIFACTS", "/tmp/e6-wave7-browser"))
        artifacts.mkdir(parents=True, exist_ok=True)
        try:
            prepare_workflow_scenario()
        except WorkflowIntegrationPending as error:
            (artifacts/"workflow-result.json").write_text(json.dumps({
                "result":"NOT_RUN", "blocker":str(error), "pass":0,"fail":0,"skip":0,
                "scope":"No persisted browser acceptance claimed; integration gate remains failing"
            }, indent=2)+"\n")
            self.fail(str(error))
        self.fail("ACTUAL_PERSISTED_BROWSER_JOURNEYS_NOT_YET_INTEGRATED")
