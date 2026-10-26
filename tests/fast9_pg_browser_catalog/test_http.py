"""Actual integrated middleware/routes deny writes before any DB access."""

from django.test import Client, SimpleTestCase, override_settings


class HTTPDenialTests(SimpleTestCase):
    def test_operator_and_catalog_write_methods_denied(self):
        client = Client(enforce_csrf_checks=True)
        for route in (
            "/dev/operator-navigation",
            "/dev/operator-navigation/history",
            "/fiqh/nodes/1?edition=7001",
            "/api/v1/fiqh/nodes/1?edition=7001",
        ):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(route=route, method=method):
                    response = client.generic(
                        method,
                        route,
                        data=b"{}",
                        content_type="application/json",
                        HTTP_HOST="127.0.0.1",
                        REMOTE_ADDR="127.0.0.1",
                    )
                    self.assertIn(response.status_code, (403, 405))

    def test_foreign_operator_peer_and_host_denied(self):
        for host, peer, status in (
            ("127.0.0.1", "203.0.113.3", 404),
            ("foreign.invalid", "127.0.0.1", 400),
        ):
            with self.subTest(host=host):
                response = self.client.get(
                    "/dev/operator-navigation/history", HTTP_HOST=host, REMOTE_ADDR=peer
                )
                self.assertEqual(response.status_code, status)

    @override_settings(FATWA_PRODUCTION=True)
    def test_production_operator_guard(self):
        self.assertEqual(
            self.client.get(
                "/dev/operator-navigation/history", HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1"
            ).status_code,
            404,
        )
