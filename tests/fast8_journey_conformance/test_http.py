"""Use existing HTTP surfaces; this lane adds no routes or writes."""

import json
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench.services import _asserted_catalog
from apps.fast6_journey.services import case_identity
from apps.fast8_journey_conformance.services import default_contract, run_conformance
from apps.reference_links.resolution import SnapshotCatalog


class ScenarioHTTPTests(SimpleTestCase):
    def get(self, route):
        return self.client.get(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")

    def test_every_stock_http_packet_matches_committed_full_scenario_pin(self):
        export = self.get("/dev/editorial-export/report.json")
        self.assertEqual(export.status_code, 200)
        entries = {r["packet"]["identity"]["case_key"]: r for r in export.json()["cases"]}
        for scenario in json.loads(default_contract())["scenarios"]:
            if scenario["kind"] != "case":
                continue
            anchor = scenario["anchor"]
            key = anchor["identity"]["case_key"]
            with self.subTest(key=key):
                queue = self.get(f"/dev/editorial-queue/{key}")
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(case_identity(queue.context["selected"].case), anchor["identity"])
                response = self.get(f"/dev/editorial-workbench/{key}?packet=json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(sha256(response.content).hexdigest(), anchor["packet_sha256"])
                self.assertEqual(response.json(), entries[key]["packet"])
                self.assertEqual(response.json()["persisted_review"]["status"], "not_loaded")

    def test_research_http_uses_same_identity_and_explicit_synthetic_lookup(self):
        report = run_conformance(synthetic_fixtures_only=True, scenario="intake-7").payload()
        scenario = report["scenarios"][0]
        catalog = SnapshotCatalog(_asserted_catalog())
        with patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup", side_effect=catalog.lookup
        ):
            response = self.get("/dev/research-bridge/intake-7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            case_identity(response.context["selected"].case), scenario["anchor"]["identity"]
        )
        self.assertEqual(
            [r["result"].catalog_url for r in response.context["references"]],
            [r["catalog_url"] for r in scenario["stages"]["research"]["references"]],
        )

    def test_service_rehearsal_support_does_not_claim_prepared_http_or_persisted_review(self):
        scenario = run_conformance(
            synthetic_fixtures_only=True, scenario="batch-synthetic-csv-1"
        ).payload()["scenarios"][0]
        self.assertEqual(scenario["stages"]["review_projection"]["status"], "PASS")
        self.assertEqual(self.get("/dev/workflow-rehearsal/batch-synthetic-csv-1").status_code, 404)
        before = self.get("/dev/editorial-workbench/intake-7?packet=json")
        self.assertEqual(self.get("/dev/workflow-rehearsal/intake-7").status_code, 200)
        self.assertEqual(
            before.content, self.get("/dev/editorial-workbench/intake-7?packet=json").content
        )
        self.assertEqual(self.get("/dev/editorial-queue/nonexistent").status_code, 404)

    def test_no_http_write_authority_or_permission_grant(self):
        permission = self.get(
            "/dev/permission-lab?actor=MUFTI&action=complete_review&resource=workflow%3A%3AIN_REVIEW"
        )
        self.assertEqual(permission.status_code, 200)
        self.assertEqual(permission.context["decision"].effect, "DENY")
        for method in ("post", "put", "patch", "delete"):
            for route in (
                "/dev/editorial-queue/intake-7",
                "/dev/editorial-workbench/intake-7?packet=json",
                "/dev/editorial-export/report.json",
                "/dev/workflow-rehearsal/intake-7",
            ):
                with self.subTest(method=method, route=route):
                    response = getattr(self.client, method)(
                        route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    )
                    self.assertEqual(response.status_code, 405)
