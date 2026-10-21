"""Route-level tests for pinned reference asset integrity; no database required."""
import base64
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

from apps.reference.asset_integrity import PINNED_PUBLIC_ASSET_MANIFEST


class ReferenceAssetIntegrityTests(SimpleTestCase):
    def get_asset(self, asset):
        return self.client.get("/assets/" + asset, HTTP_HOST="localhost")

    def test_all_pinned_assets_match_manifest_and_served_bytes(self):
        for asset, (expected_size, expected_sha256) in PINNED_PUBLIC_ASSET_MANIFEST.items():
            with self.subTest(asset=asset):
                filename = finders.find(asset)
                self.assertIsNotNone(filename)
                source = Path(filename).read_bytes()
                self.assertEqual(len(source), expected_size)
                self.assertEqual(sha256(source).hexdigest(), expected_sha256)
                response = self.get_asset(asset)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, source)
                self.assertEqual(
                    response["Content-Type"],
                    "text/css; charset=utf-8"
                    if asset.endswith(".css")
                    else "text/javascript; charset=utf-8",
                )

    def test_htmx_pin_matches_installed_distribution_record(self):
        dist = distribution("django-htmx")
        self.assertEqual(dist.version, "1.29.0")
        relative = "django_htmx/static/django_htmx/htmx-2.min.js"
        matches = [
            entry for entry in (dist.files or [])
            if str(entry).replace("\\", "/") == relative
        ]
        self.assertEqual(len(matches), 1)
        entry = matches[0]
        self.assertEqual(entry.hash.mode, "sha256")
        data = dist.locate_file(entry).read_bytes()
        encoded = base64.urlsafe_b64encode(sha256(data).digest()).decode().rstrip("=")
        self.assertEqual(encoded, entry.hash.value)
        self.assertEqual(len(data), 51238)
        self.assertEqual(
            sha256(data).hexdigest(),
            PINNED_PUBLIC_ASSET_MANIFEST["django_htmx/htmx-2.min.js"][1],
        )

    def test_manifest_cannot_be_mutated_at_runtime(self):
        with self.assertRaises(TypeError):
            PINNED_PUBLIC_ASSET_MANIFEST["reference/style.css"] = (1, "0" * 64)

    def test_missing_pinned_asset_fails_closed(self):
        with patch("django.contrib.staticfiles.finders.find", return_value=None):
            response = self.get_asset("reference/style.css")
        self.assertEqual(response.status_code, 404)

    def test_drifted_pinned_asset_fails_closed(self):
        filename = finders.find("reference/style.css")
        original = Path(filename).read_bytes()
        altered = bytearray(original)
        altered[0] ^= 1
        with TemporaryDirectory() as directory:
            candidate = Path(directory) / "style.css"
            candidate.write_bytes(altered)
            with patch("django.contrib.staticfiles.finders.find", return_value=str(candidate)):
                response = self.get_asset("reference/style.css")
        self.assertEqual(response.status_code, 404)

    def test_unlisted_reference_asset_is_rejected(self):
        response = self.get_asset("reference/not-in-manifest.js")
        self.assertEqual(response.status_code, 404)

    def test_safe_methods_are_preserved(self):
        response = self.get_asset("reference/style.css")
        self.assertEqual(response.status_code, 200)
        head = self.client.head("/assets/reference/style.css", HTTP_HOST="localhost")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        for method in ("post", "put", "patch", "delete", "options", "trace"):
            with self.subTest(method=method):
                denied = getattr(self.client, method)(
                    "/assets/reference/style.css", HTTP_HOST="localhost"
                )
                self.assertEqual(denied.status_code, 405)
                self.assertEqual(denied["Allow"], "GET, HEAD")
