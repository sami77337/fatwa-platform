"""Focused HTTP guard tests plus executable harness, without database creation."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings

from tools.fast8_browser_conformance.run import (
    bounded_catalog_preflight,
    catalog_preflight,
    fixture_contract,
    run,
)

ROOT = Path(__file__).resolve().parents[2]
ROUTES = (
    "/dev/editorial-queue/history",
    "/dev/editorial-search?q=history&source=record",
    "/dev/research-bridge/history",
    "/dev/reference-triage/history",
    "/dev/editorial-workbench/history?revision=1",
    "/dev/editorial-workbench/history?packet=json",
    "/dev/editorial-export",
    "/dev/editorial-export/report.json",
)


class GuardedHTTPTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_each_route_denies_all_write_methods(self):
        for route in ROUTES:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(route=route, method=method):
                    response = self.client.generic(
                        method,
                        route,
                        data=b"{}",
                        content_type="application/json",
                        HTTP_HOST="127.0.0.1",
                        REMOTE_ADDR="127.0.0.1",
                    )
                    self.assertIn(response.status_code, (403, 405))

    def test_each_route_rejects_foreign_peer_and_host(self):
        for route in ROUTES:
            for host, peer, status in (
                ("127.0.0.1", "203.0.113.42", 404),
                ("fast8-foreign.invalid", "127.0.0.1", 400),
            ):
                with self.subTest(route=route, host=host, peer=peer):
                    response = self.client.get(route, HTTP_HOST=host, REMOTE_ADDR=peer)
                    self.assertEqual(response.status_code, status)

    @override_settings(FATWA_PRODUCTION=True)
    def test_each_route_is_closed_in_production(self):
        for route in ROUTES:
            with self.subTest(route=route):
                self.assertEqual(
                    self.client.get(
                        route, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1"
                    ).status_code,
                    404,
                )

    def test_existing_read_contracts_remain_available_and_private(self):
        for route in ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response.headers["Cache-Control"])


class HarnessTests(SimpleTestCase):
    def test_absent_postgresql_never_connects_or_claims_acceptance(self):
        with (
            patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "0"}),
            patch("apps.intake_workflow.guards.require_owned_database") as guard,
        ):
            self.assertEqual(catalog_preflight()["result"], "NOT_RUN")
            guard.assert_not_called()

    def test_supplied_untrusted_postgresql_is_not_a_pass(self):
        from apps.intake_workflow.guards import SyntheticWriteDenied

        with (
            patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "1"}),
            patch(
                "apps.intake_workflow.guards.require_owned_database",
                side_effect=SyntheticWriteDenied("DATABASE_UNAVAILABLE_OR_UNTRUSTED"),
            ),
        ):
            self.assertEqual(catalog_preflight()["result"], "NOT_RUN")

    def test_extra_edition_or_row_fails_before_retrieving_catalog_text(self):
        for counts in ((1, 2, 3), (1, 1, 4), (2, 1, 3)):
            with (
                self.subTest(counts=counts),
                patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "1"}),
                patch("apps.intake_workflow.guards.require_owned_database"),
                patch("apps.reference.models.ReferenceWork.objects.count", return_value=counts[0]),
                patch(
                    "apps.reference.models.ReferenceEdition.objects.count", return_value=counts[1]
                ),
                patch(
                    "apps.reference.models.ReferenceHeading.objects.count", return_value=counts[2]
                ),
                patch("apps.reference.services.list_books") as books,
            ):
                self.assertEqual(catalog_preflight()["result"], "FAIL")
                books.assert_not_called()

    def test_wrong_catalog_identity_fails_without_substituting_a_fixture(self):
        with (
            patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "1"}),
            patch("apps.intake_workflow.guards.require_owned_database"),
            patch("apps.reference.models.ReferenceWork.objects.count", return_value=1),
            patch("apps.reference.models.ReferenceEdition.objects.count", return_value=1),
            patch("apps.reference.models.ReferenceHeading.objects.count", return_value=3),
            patch("apps.reference.services.list_books") as books,
        ):
            books.return_value.total = 1
            books.return_value.items = [{"id": 7002}]
            self.assertEqual(catalog_preflight()["result"], "FAIL")

    def test_unresponsive_catalog_preflight_is_bounded_not_passed(self):
        with (
            patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "1"}),
            patch(
                "tools.fast8_browser_conformance.run.subprocess.run",
                side_effect=subprocess.TimeoutExpired("synthetic-preflight", 15),
            ),
        ):
            self.assertEqual(bounded_catalog_preflight()["result"], "NOT_RUN")

    def test_missing_chrome_is_not_run_with_cleanup_and_no_passed_checks(self):
        with patch.dict(
            os.environ,
            {
                "FAST8_EXISTING_SYNTHETIC_PG": "0",
                "FATWA_FASTBUILD_BROWSER": str(
                    ROOT / "tools/fast8_browser_conformance/no-browser.exe"
                ),
            },
        ):
            report = run()
        self.assertEqual(report["browser"], "NOT_RUN")
        self.assertEqual(report["result"], "NOT_RUN")
        self.assertEqual(report["checks"], [])
        self.assertEqual(report["cleanup"]["result"], "PASS")

    def test_expected_revision_is_historical_and_has_exact_crlf(self):
        contract = fixture_contract()
        packet = contract["packets"]["history"]
        self.assertNotEqual(contract["search"]["revision"], packet["selection"]["revision"])
        self.assertTrue(any("\r\n" in row["answer"] for row in packet["snapshots"]))
        self.assertEqual(contract["search"]["source_sha256"], packet["source"]["text_sha256"])

    def test_deterministic_node_negative_tests(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "NOT_RUN: Node unavailable for mandatory harness tests")
        result = subprocess.run(
            [
                node,
                "--test",
                "--test-reporter=tap",
                str(Path(__file__).with_name("policy.test.mjs")),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_protected_browser_operator_flow(self):
        # Explicitly DB-free here. The CLI separately opts into an existing owned
        # PostgreSQL source, never Django's create/migrate/flush test lifecycle.
        with patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "0"}):
            report = run()
        print(json.dumps(report, ensure_ascii=True))
        if report["browser"] == "NOT_RUN":
            self.skipTest("NOT_RUN: protected Chrome/Node unavailable; no browser PASS")
        self.assertEqual(report["browser"], "PASS", report)
        self.assertEqual(report["result"], "NOT_RUN")
        self.assertEqual(len(report["checks"]), 17)
        self.assertEqual(report["cleanup"]["result"], "PASS")
