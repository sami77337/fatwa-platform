"""Protected native developer explorer, JSON and exact download/revocation evidence."""

import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.private_media.filesystem import FileSystemStorage
from apps.research_library import browser_tests as library_browser

from .test_support import FEATURES, TEXT, APIFixture

OUT = Path(".local/qa/functional-continuation/material-api-browser")


@override_settings(**FEATURES)
class MaterialAPIBrowserTests(APIFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = library_browser.LibraryBrowserTests.sync

    def capture(self, page, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            filename = f"{name}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_native_developer_search_exact_json_original_and_current_revocation(self):
        from playwright.sync_api import sync_playwright

        folder = self.enterContext(tempfile.TemporaryDirectory(prefix="api-browser-"))
        storage = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
        self.enterContext(override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage))
        row = self.source()
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {"status": "ERROR", "sandbox": True, "widths": [320, 1280],
                 "screenshots": [], "page_errors": [], "external_requests": []}
        origin = urlsplit(self.live_server_url).netloc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"), chromium_sandbox=True, args=["--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width": 320, "height": 900}, accept_downloads=True)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            def local_only(route):
                url = urlsplit(route.request.url)
                if url.scheme == "http" and url.netloc == origin:
                    route.continue_()
                else:
                    proof["external_requests"].append("blocked")
                    route.abort()
            context.route("**/*", local_only)
            page = context.new_page()
            page.on("pageerror", lambda error: proof["page_errors"].append(type(error).__name__))
            try:
                self.assertEqual(page.goto(self.live_server_url + "/library-preview/materials/").status, 200)
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("link", name="واجهة المواد للمطورين", exact=True).click()
                page.locator("#api-query").fill("قراءة")
                page.locator("#api-kind").select_option("BOOK")
                with page.expect_navigation(wait_until="domcontentloaded") as searched:
                    page.get_by_role("button", name="بحث المواد", exact=True).click()
                self.assertEqual(searched.value.status, 200)
                self.assertEqual(page.locator("article.card").count(), 1)
                self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                self.capture(page, "native-allowed-material-search", proof)
                with page.expect_navigation(wait_until="domcontentloaded") as opened:
                    page.locator("a.api-record").click()
                actual = opened.value.json()["material"]
                self.assertEqual(actual["version_sha256"], row["digest"])
                self.assertEqual(actual["material_id"], row["public_id"])
                self.assertNotIn("private-source-name", str(actual))
                page.go_back(wait_until="domcontentloaded")
                with page.expect_download() as transfer:
                    page.locator("a.api-original").click()
                downloaded = transfer.value
                self.assertIsNone(downloaded.failure())
                output = OUT / "original.txt"
                downloaded.save_as(str(output))
                self.assertEqual(output.read_bytes(), TEXT)
                with page.expect_navigation(wait_until="domcontentloaded") as found:
                    page.get_by_role("button", name="فتح نتيجة JSON", exact=True).click()
                self.assertEqual(found.value.json()["results"][0]["material_id"], row["public_id"])
                page.go_back(wait_until="domcontentloaded")
                self.authority.denied.add("DOWNLOAD")
                page.reload(wait_until="domcontentloaded")
                self.assertEqual(page.locator("a.api-original").count(), 0)
                denied = context.request.get(self.live_server_url + actual["links"]["original"])
                self.assertEqual(denied.status, 404)
                self.authority.denied.add("RELEASE")
                page.reload(wait_until="domcontentloaded")
                self.assertEqual(page.locator("article.card").count(), 0)
                self.capture(page, "withdrawn-allowed-material-search", proof)
                self.assertEqual(context.request.get(self.live_server_url + self.url(row)).status, 404)
                self.assertEqual(proof["page_errors"], [])
                self.assertEqual(proof["external_requests"], [])
                proof.update(status="PASS", actual_native_search=True, exact_version_sha256=row["digest"],
                    exact_original={"file": output.name, "sha256": sha256(TEXT).hexdigest(), "size": len(TEXT)},
                    current_download_and_release_denied=True, private_identifiers_absent=True)
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
                (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
