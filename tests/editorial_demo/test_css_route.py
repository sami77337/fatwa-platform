"""Scoped HTTP regressions for the existing loopback-only stylesheet route.

Run under Django's Wave7/standard test settings, not in the stdlib-only lane.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.editorial_demo import asset_integrity as guard


class EditorialCssRouteTests(SimpleTestCase):
    url = "/dev/editorial-preview/style.css"

    def request(self, method="get", **kwargs):
        return getattr(self.client, method)(self.url, HTTP_HOST="localhost", **kwargs)

    def test_success_bytes_and_safe_methods(self):
        expected = guard.verified_preview_css()
        get = self.request()
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.content, expected)
        self.assertEqual(get["Content-Type"], "text/css; charset=utf-8")
        self.assertEqual(get["Cache-Control"], "no-store")
        head = self.request("head")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        for method in ("post", "put", "patch", "delete", "options", "trace"):
            with self.subTest(method=method):
                blocked = self.request(method)
                self.assertEqual(blocked.status_code, 405)
                self.assertEqual(blocked["Allow"], "GET, HEAD")

    def test_missing_or_modified_css_denied(self):
        original = guard.verified_preview_css()
        with TemporaryDirectory() as directory:
            target = Path(directory) / "preview.css"
            with patch.object(guard, "PREVIEW_CSS_PATH", target):
                self.assertEqual(self.request().status_code, 404)
                target.write_bytes(original + b"/* modified */")
                self.assertEqual(self.request().status_code, 404)
                target.write_bytes(original)
                self.assertEqual(self.request().status_code, 200)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_host_peer_and_production_lock_unchanged(self):
        self.assertEqual(self.request(REMOTE_ADDR="192.0.2.15").status_code, 404)
        self.assertEqual(self.client.get(self.url, HTTP_HOST="example.invalid").status_code, 404)
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
            self.assertEqual(self.request().status_code, 404)
