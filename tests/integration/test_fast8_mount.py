"""Exercise the mounted route through the real project URL configuration."""

import os
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse


@override_settings(ROOT_URLCONF="config.urls")
class OperatorMountTests(SimpleTestCase):
    routes = (
        "/dev/operator-navigation",
        "/dev/operator-navigation/history",
        "/dev/operator-navigation/style.css",
    )

    def test_local_get_head_and_exact_service_destinations(self):
        self.assertEqual(reverse("fast8_operator_nav:index"), self.routes[0])
        for host, peer in (
            ("localhost", "127.0.0.1"),
            ("127.0.0.1", "127.0.0.1"),
            ("[::1]", "::1"),
        ):
            for route in self.routes:
                for method in ("get", "head"):
                    with self.subTest(host=host, route=route, method=method):
                        response = getattr(self.client, method)(
                            route, HTTP_HOST=host, REMOTE_ADDR=peer
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response["Cache-Control"], "no-store")
                        if method == "head":
                            self.assertEqual(response.content, b"")
        response = self.client.get(
            self.routes[1] + "?revision=4", HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
        )
        self.assertContains(response, "/dev/editorial-workbench/history?revision=4#snapshot")
        self.assertContains(response, "/dev/operator-navigation/history?revision=7")

    def test_denials_precede_catalog_access(self):
        with patch("apps.fast8_operator_nav.views.build_queue_catalog") as build:
            for route in self.routes:
                for method in ("get", "head"):
                    for host, peer in (
                        ("testserver", "127.0.0.1"),
                        ("localhost", "192.0.2.1"),
                        ("localhost", "invalid"),
                    ):
                        response = getattr(self.client, method)(
                            route, HTTP_HOST=host, REMOTE_ADDR=peer
                        )
                        self.assertEqual(response.status_code, 404)
                    for settings in (
                        {"FATWA_PRODUCTION": True},
                        {"SETTINGS_MODULE": "config.settings.production"},
                    ):
                        with override_settings(**settings):
                            self.assertEqual(
                                getattr(self.client, method)(
                                    route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                                ).status_code,
                                404,
                            )
                    with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                        self.assertEqual(
                            getattr(self.client, method)(
                                route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                            ).status_code,
                            404,
                        )
                for method in ("post", "put", "patch", "delete", "options", "trace"):
                    self.assertEqual(
                        getattr(self.client, method)(
                            route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                        ).status_code,
                        405,
                    )
            build.assert_not_called()

    def test_malformed_or_unknown_selectors_never_select_another_case(self):
        for suffix, status in (
            ("?q=a&q=b", 400),
            ("?page=01", 400),
            ("?revision=1", 400),
            ("?q=%00", 400),
            ("/history?revision=04", 400),
            ("/history?revision=3", 404),
            ("/absent", 404),
            ("/style.css?next=external", 400),
        ):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    self.routes[0] + suffix, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response["Cache-Control"], "no-store")
