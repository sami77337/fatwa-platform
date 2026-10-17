"""Real loopback HTTP checks for the exact assets the browser must execute."""
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from django.conf import settings

from .live_server import SyntheticLiveServerTestCase
from .support import require_disposable_database

require_disposable_database()


class LiveAssetTests(SyntheticLiveServerTestCase):
    def test_catalog_assets_are_actual_files_with_executable_mime(self):
        for name in ["catalog.js", "django-api.mjs", "tree.js", "style.css", "catalog.css"]:
            with self.subTest(asset=name):
                try:
                    response = urlopen(self.live_server_url + "/assets/reference/" + name, timeout=5)
                except HTTPError as error:
                    response = error
                with response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(response.headers.get_content_type(),
                                  {"text/css"} if name.endswith(".css") else
                                  {"text/javascript", "application/javascript"})
                    original = Path(settings.BASE_DIR, "apps/reference/static/reference", name).read_bytes()
                    self.assertEqual(response.read(), original, "Asset must be original file bytes, not an HTML fallback")

    def test_missing_asset_is_404_not_html_success(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.live_server_url + "/assets/reference/e6-nonexistent.js", timeout=5)
        self.assertEqual(caught.exception.code, 404)
