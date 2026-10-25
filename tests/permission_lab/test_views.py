"""The local inspector displays real deny decisions without database access."""

import os
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class PermissionLabViewsTests(SimpleTestCase):
    url = "/dev/permission-lab"
    selection = {
        "actor": "MUFTI",
        "action": "start_review",
        "resource": "workflow::UNREVIEWED",
    }

    def get(self, url=None, **extra):
        return self.client.get(
            url or self.url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra
        )

    def test_connected_rtl_catalog_is_read_only_and_preserves_gate_status(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for marker in (
            'lang="ar"',
            'dir="rtl"',
            'href="#main-content"',
            'for="actor"',
            'for="action"',
            'for="resource"',
            'method="get"',
            'href="/dev/editorial-dashboard"',
            "MUFTI",
            "ORGANIZER_ADMIN",
            "ORGANIZER",
            "synthetic::answer",
            "workflow::UNREVIEWED",
            "Gate B NOT_PASSED",
            "C/D/E HOLD",
            "Phase01 BLOCKED",
            "SCOPE_DEVIATION_HOLD",
            "NOT_DEPLOYED",
            "70",
            "58",
        ):
            self.assertContains(response, marker)
        self.assertIsNone(response.context["decision"])
        self.assertNotContains(response, "<script")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_exact_selection_uses_connected_decision_and_shows_all_reasons(self):
        response = self.get(data=self.selection)
        self.assertEqual(response.status_code, 200)
        decision = response.context["decision"]
        self.assertEqual(decision.effect, "DENY")
        self.assertIs(decision.allowed, False)
        self.assertTrue(decision.valid_combination)
        self.assertEqual(decision.workflow_target, "IN_REVIEW")
        self.assertGreater(len(decision.reasons), 0)
        self.assertEqual(response.context["selected"], self.selection)
        for value in self.selection.values():
            self.assertContains(response, value)
        for reason in decision.reasons:
            self.assertContains(response, reason.code)
            self.assertContains(response, reason.message)
        self.assertContains(response, "DENY")
        self.assertContains(response, "IN_REVIEW")

    def test_malformed_queries_never_reach_catalog_or_evaluator(self):
        valid = "actor=MUFTI&action=start_review&resource=workflow::UNREVIEWED"
        for query in (
            "actor=MUFTI",
            "action=start_review&resource=workflow::UNREVIEWED",
            valid + "&actor=MUFTI",
            valid + "&role=MUFTI",
            valid.replace("MUFTI", ""),
            valid.replace("MUFTI", "x" * 97),
            valid.replace("MUFTI", "%00"),
            valid.replace("MUFTI", "%0A"),
            valid.replace("MUFTI", "<script>"),
            valid.replace("MUFTI", "../secret"),
            valid.replace("MUFTI", "%20MUFTI"),
            valid.replace("MUFTI", "%E2%80%AE"),
            "&".join(f"x{i}=y" for i in range(17)),
            "&".join(f"x{i}=y" for i in range(200)),
        ):
            with (
                self.subTest(query=query[:100]),
                patch("apps.permission_lab.views.build_catalog") as build,
                patch("apps.permission_lab.views.evaluate") as evaluate,
            ):
                response = self.get(self.url + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "DENY", status_code=400)
                build.assert_not_called()
                evaluate.assert_not_called()
        # The existing global middleware owns its stricter pre-view response
        # format for raw queries over 4096 bytes.
        with (
            patch("apps.permission_lab.views.build_catalog") as build,
            patch("apps.permission_lab.views.evaluate") as evaluate,
        ):
            response = self.get(self.url + "?" + "&".join(f"x{i}=y" for i in range(1200)))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "invalid_query"})
            build.assert_not_called()
            evaluate.assert_not_called()

    def test_unknown_catalog_values_never_reach_evaluator(self):
        for key in self.selection:
            with self.subTest(key=key), patch("apps.permission_lab.views.evaluate") as evaluate:
                response = self.get(data={**self.selection, key: "unknown"})
                self.assertEqual(response.status_code, 400)
                evaluate.assert_not_called()

    def test_source_failures_are_explicit_denials_without_internal_details(self):
        from apps.permission_lab.sources import SourceUnavailable

        for target in ("build_catalog", "evaluate"):
            with patch(
                "apps.permission_lab.views." + target,
                side_effect=SourceUnavailable("internal-secret"),
            ):
                response = self.get(data=self.selection)
            self.assertContains(response, "DENY", status_code=503)
            self.assertNotContains(response, "internal-secret", status_code=503)
            self.assertContains(response, "NOT_DEPLOYED", status_code=503)
            self.assertEqual(response["Cache-Control"], "no-store")

    def test_local_guard_rejects_hosts_peers_production_and_forwarded_spoofing(self):
        for url in (self.url, self.url + "/style.css"):
            with patch("apps.permission_lab.views.build_catalog") as build:
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "192.0.2.1"),
                    ("localhost", ""),
                    ("localhost", "invalid"),
                ):
                    response = self.client.get(
                        url,
                        HTTP_HOST=host,
                        REMOTE_ADDR=peer,
                        HTTP_X_FORWARDED_FOR="127.0.0.1",
                        HTTP_X_FORWARDED_HOST="localhost",
                    )
                    self.assertEqual(response.status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(url).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(url).status_code, 404)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(url).status_code, 404)
                build.assert_not_called()

    def test_only_safe_methods_are_available_on_page_and_stylesheet(self):
        for url in (self.url, self.url + "/style.css"):
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
                with patch("apps.permission_lab.views.build_catalog") as build:
                    response = self.client.generic(
                        method, url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    )
                    self.assertEqual(response.status_code, 405)
                    build.assert_not_called()
            response = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_stylesheet_supports_focus_mobile_and_no_query_parameters(self):
        response = self.get(self.url + "/style.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response["Content-Type"])
        self.assertContains(response, ":focus-visible")
        self.assertContains(response, "@media")
        self.assertEqual(self.get(self.url + "/style.css?path=secret").status_code, 400)
