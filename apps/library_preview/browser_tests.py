"""Real Chromium anonymous preview with no staff credentials or private links."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import connections
from django.test import LiveServerTestCase, override_settings

from .tests import ENABLED, PreviewFixture


@override_settings(**ENABLED)
class PreviewBrowserTests(PreviewFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_anonymous_rtl_search_reference_return_and_revocation(self):
        from playwright.sync_api import sync_playwright

        errors, external, private_requests, results = [], [], [], []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
                headless=True,
            )
            try:
                for width in (320, 1280):
                    context = browser.new_context(viewport={"width": width, "height": 900})
                    page = context.new_page()
                    page.on("pageerror", lambda err: errors.append(str(err)))

                    def observe(request):
                        url = urlsplit(request.url)
                        if url.netloc != urlsplit(self.live_server_url).netloc:
                            external.append(request.url)
                        if url.path.startswith("/casework/"):
                            private_requests.append(request.url)

                    page.on("request", observe)
                    response = page.goto(self.live_server_url + "/library-preview/")
                    self.assertEqual(response.status, 200)
                    page.locator("#q").fill("عُنْوان")
                    page.locator("#category").select_option("تصنيف تجريبي")
                    page.locator("#material").select_option("reference")
                    page.get_by_role("button", name="بحث وتصفية").click()
                    self.assertIn("عدد النتائج: 1", page.content())
                    page.get_by_role("link", name="عنوان تجريبي", exact=True).click()
                    self.assertIn("نص محرر مسموح", page.content())
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    self.assertIn("مادة درس أو تفريغ مرتبطة خاصة", page.content())
                    self.assertNotIn(self.transcript_source_id, page.content())
                    self.assertEqual(page.locator('a[href*="transcript"]').count(), 0)
                    page.get_by_role("link", name="علاقة موثقة: فَرْعٌ تَجْرِيبِيّ", exact=True).click()
                    self.assertIn("الجزء والصفحة المطبوعة", page.content())
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    page.get_by_role("link", name="العودة إلى عنوان تجريبي", exact=True).click()
                    page.get_by_role(
                        "link", name="العودة إلى نتائج البحث والتصفية", exact=True
                    ).click()
                    self.assertEqual(page.locator("#q").input_value(), "عُنْوان")
                    self.assertEqual(page.locator("#category").input_value(), "تصنيف تجريبي")
                    self.assertEqual(page.locator("#material").input_value(), "reference")
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    page.keyboard.press("Tab")
                    self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                    self.assertNotIn("PRIVATE", page.content())
                    self.assertEqual(context.cookies(), [])
                    results.append(
                        {
                            "width": width,
                            "rtl": True,
                            "anonymous": True,
                            "return_filters": True,
                            "overflow": False,
                        }
                    )
                    context.close()
                page = browser.new_page()

                def withdraw_in_thread():
                    try:
                        self.withdraw()
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(withdraw_in_thread).result()
                closed = page.goto(self.live_server_url + self.detail_url)
                self.assertEqual(closed.status, 404)
                self.assertNotIn("نص محرر مسموح", page.content())
                source = page.goto(self.live_server_url + self.source_url)
                self.assertEqual(source.status, 404)
                page.goto(self.live_server_url + "/library-preview/")
                self.assertIn("عدد النتائج: 0", page.content())
                output = Path(".local/qa/library-preview")
                output.mkdir(parents=True, exist_ok=True)
                (output / "browser.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
                            "results": results,
                            "withdrawal_detail_and_source": 404,
                            "errors": errors,
                            "external_requests": external,
                            "private_requests": private_requests,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
        self.assertEqual(private_requests, [])
