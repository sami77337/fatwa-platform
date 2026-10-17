"""The same staticfiles-aware live server as browser tests; original bytes only."""
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from .target import require_lane_configuration

require_lane_configuration()


class E6LiveServer(StaticLiveServerTestCase):
    host = "127.0.0.1"


class AssetTests(E6LiveServer):
    def test_installed_assets_are_200_with_correct_mime_and_original_bytes(self):
        for name in ["catalog.js", "django-api.mjs", "tree.js", "catalog.css", "style.css"]:
            with self.subTest(name=name), urlopen(self.live_server_url + "/assets/reference/" + name, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(response.headers.get_content_type(), {"text/css"} if name.endswith(".css")
                              else {"text/javascript", "application/javascript"})
                self.assertEqual(response.read(), Path(settings.BASE_DIR,
                    "apps/reference/static/reference", name).read_bytes())

    def test_missing_asset_is_404_not_successful_html_fallback(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.live_server_url + "/assets/reference/e6-wave7-missing.js", timeout=5)
        self.assertEqual(caught.exception.code, 404)
