"""Actual Chrome against Django; database access is forbidden by SimpleTestCase."""

import base64
import json
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from django.test import SimpleTestCase

from apps.editorial_export.services import build_export
from apps.editorial_queue.services import build_queue_catalog
from tests.acceptance.fastbuild.test_browser import editorial_server


class Fast4BrowserTests(SimpleTestCase):
    def test_head_responses_are_empty_and_private(self):
        # The bare wsgiref browser harness sends HEAD bodies, unlike Django's
        # runserver transport. Check actual view/middleware semantics with the
        # Django client; do not claim browser HEAD transport acceptance here.
        for feature in ("dashboard", "search", "followup", "export"):
            with self.subTest(feature=feature):
                response = self.client.head(
                    f"/dev/editorial-{feature}",
                    HTTP_HOST="localhost",
                    REMOTE_ADDR="127.0.0.1",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"")
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_connected_fast4_pages_preserve_exact_synthetic_sources(self):
        bundle = build_export(synthetic_fixtures_only=True)
        expected = {
            "files": {
                name: {
                    "base64": base64.b64encode(raw).decode("ascii"),
                    "sha256": sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
                for name, raw in bundle.files
            },
            "keys": [row.case.key for row in build_queue_catalog().rows],
        }
        with tempfile.TemporaryDirectory(prefix="fatwa-fast4-expected-") as folder:
            expectation = Path(folder) / "expected.json"
            expectation.write_text(json.dumps(expected), encoding="utf-8")
            with editorial_server() as origin:
                result = subprocess.run(
                    [
                        "node",
                        str(Path(__file__).with_name("browser.mjs")),
                        origin,
                        str(expectation),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=180,
                )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
