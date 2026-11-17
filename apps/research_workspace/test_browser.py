"""One local Chromium journey; fixture-only sources, no external network."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .tests import SETTINGS, ResearchFixture

OUT = Path(".local/qa/v11-research")


@override_settings(**SETTINGS)
class ResearchBrowserTests(ResearchFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def run():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def click(self, page, name, code=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            target = page.get_by_role("button", name=name, exact=True)
            target.focus()
            target.press("Enter")
        self.assertEqual(navigation.value.status, code, page.locator("main").inner_text()[:500])
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, label):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)

    def test_reference_transcript_media_and_human_citation_roundtrip(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        self.with_media()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            external, errors, failed = [], [], []

            def route(r):
                if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                    external.append(r.request.url)
                    r.abort()
                else:
                    r.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: failed.append(r.url) if r.status >= 400 else None)
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                self.click(page, "دخول المكتب")
                self.click(page, "البحث في مصادر القضية")
                page.locator("#kind").select_option("TRANSCRIPT")
                self.click(page, "البحث في المصادر المصرح بها")
                self.click(page, "فتح المصدر: سؤال من التفريغ المرتبط " + self.transcript_source_id)
                self.assertIn(self.transcript_text, page.locator("main").inner_text())
                self.capture(page, "transcript")
                self.click(page, "العودة إلى نتائج البحث نفسها")
                self.assertEqual(page.locator("#kind").input_value(), "TRANSCRIPT")
                page.locator("#kind").select_option("MEDIA")
                self.click(page, "البحث في المصادر المصرح بها")
                with page.expect_download() as download:
                    page.get_by_role(
                        "button", name="تنزيل الوسيط المصرح: answer.wav", exact=True
                    ).click()
                from apps.answer_media.tests import audio_fixture

                self.assertEqual(Path(download.value.path()).read_bytes(), audio_fixture()["raw"])
                page.locator("#kind").select_option("REFERENCE")
                page.locator("#edition").select_option(str(self.catalog_id))
                page.locator("#query").fill("فرع")
                self.click(page, "البحث في المصادر المصرح بها")
                self.capture(page, "arabic-results")
                # Existing fixture row2 is already cited; select its distinct root row5.
                row = page.locator(f'article[data-resource-id="{self.catalog_id}:5"]')
                with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                    row.get_by_role("button").focus()
                    row.get_by_role("button").press("Enter")
                self.assertEqual(navigation.value.status, 200)
                self.assertIn("لا يوجد متن كتاب", page.locator("main").inner_text())
                self.capture(page, "exact-source")
                page.locator("#note").fill("مراجعة بشرية اصطناعية للمصدر")
                page.locator('input[name="confirm"]').check()
                self.click(page, "إضافة إحالة دقيقة للجواب المحفوظ")
                self.assertIn("يلزم اعتماد بشري جديد", page.locator("main").inner_text())
                self.assertEqual(page.locator("#query").input_value(), "فرع")
                self.capture(page, "saved-revision")
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                self.assertEqual(failed, [])
            finally:
                browser.close()
