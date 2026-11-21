"""Protected Chromium uses the actual campaign tab, forms, source and stale rebuild."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings
from django.utils.html import escape

from apps.casework.models import CaseEvent, CaseSource

from .models import SearchGeneration
from .test_support import FEATURES, SearchFixture

OUT = Path(".local/qa/functional-continuation/canonical-search-browser")


@override_settings(**FEATURES)
class CanonicalSearchBrowserTests(SearchFixture, LiveServerTestCase):
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

    def form(self, page, action):
        form = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(form.count(), 1)
        return form

    def submit(self, page, action, *, code=200, form=None):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button = (form or self.form(page, action)).locator("button").first
            button.focus()
            button.press("Enter")
        self.assertEqual(navigation.value.status, code)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))
        return navigation.value

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def query(self, page, value, mode):
        page.locator("#canonical-query").fill(value)
        page.locator("#canonical-mode").select_option(mode)
        self.submit(page, "cs_search")

    def test_native_literal_fts_fuzzy_exact_source_stale_rebuild_and_current_revocation(self):
        from playwright.sync_api import sync_playwright

        self.answer()
        before = CaseEvent.objects.count()
        OUT.mkdir(parents=True, exist_ok=True)
        errors, external = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True)

            def route(request):
                url = urlsplit(request.request.url)
                if url.scheme != "http" or url.netloc != urlsplit(self.live_server_url).netloc:
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.submit(page, "cs_open")
                self.assertEqual(
                    page.locator("#canonical-search-case").inner_text(), self.receipt["public_ref"]
                )
                self.submit(page, "cs_rebuild")
                self.assertEqual(self.sync(lambda: SearchGeneration.objects.count()), 1)
                self.query(page, "المعاملات المالية", "FTS")
                self.assertEqual(page.locator(".canonical-hit").count(), 2)
                self.capture(page, "fts-current-sources")
                self.query(page, "المعاملات المالية", "LITERAL")
                self.assertEqual(page.locator(".canonical-hit").count(), 0)
                self.capture(page, "literal-distinction")
                self.query(page, "المعاملاتت", "FUZZY")
                self.assertEqual(page.locator(".canonical-hit").count(), 2)
                self.capture(page, "explicit-fuzzy")
                form = page.locator('.canonical-hit[data-kind="QUESTION"] form').first
                source_response = self.submit(page, "cs_source", form=form)
                # The response and canonical source retain CRLF. HTML parsing
                # normalizes literal CR/CRLF to LF in text nodes (not the data).
                self.assertIn(escape(self.question).encode(), source_response.body())
                self.assertEqual(
                    page.locator("#canonical-source-text").text_content(),
                    self.question.replace("\r\n", "\n").replace("\r", "\n"),
                )
                self.capture(page, "exact-original")
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before)
                self.query(page, "المعاملات المالية", "FTS")
                self.sync(lambda: self.answer("نسخة بشرية اصطناعية أحدث عن الإيداع"))
                self.submit(page, "cs_source", code=409)
                page.goto(self.live_server_url + "/casework/staff/")
                self.submit(page, "open")
                self.submit(page, "cs_open")
                self.assertIn("قديم", page.locator("#search-index-status").inner_text())
                self.submit(page, "cs_rebuild")
                self.query(page, "الإيداع", "FTS")
                self.assertEqual(page.locator(".canonical-hit").count(), 1)
                self.capture(page, "rebuilt-current-answer")
                self.authority.denied.add("OPEN")
                self.submit(page, "cs_source", code=409)
                self.assertNotIn("نسخة بشرية اصطناعية", page.locator("body").inner_text())
                self.assertEqual(self.sync(lambda: SearchGeneration.objects.count()), 2)
                self.assertEqual(
                    self.sync(
                        lambda: (
                            CaseSource.objects.get(case_id=self.common["case_id"]).original_question
                        )
                    ),
                    self.question,
                )
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before + 1)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "protected_browser": True,
                            "widths": [320, 1280],
                            "modes": ["LITERAL", "FTS", "FUZZY"],
                            "exact_original_open": True,
                            "stale_source_denied": True,
                            "explicit_rebuild": True,
                            "current_access_revocation": True,
                            "original_question_unchanged": True,
                            "page_errors": 0,
                            "external_requests": 0,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
