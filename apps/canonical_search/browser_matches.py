"""Protected native forms open real source ranges and reauthorize every movement."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import CaseEvent, CaseSource

from . import browser_tests as native_search
from . import test_match_http as native_html
from .test_support import FEATURES, SearchFixture
from .text import text_digest

OUT = Path(".local/qa/functional-continuation/search-match-browser")


@override_settings(**FEATURES)
class SearchMatchBrowserTests(SearchFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = native_search.CanonicalSearchBrowserTests.sync
    form = native_search.CanonicalSearchBrowserTests.form
    submit = native_search.CanonicalSearchBrowserTests.submit
    query = native_search.CanonicalSearchBrowserTests.query

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.locator("#canonical-active-match").scroll_into_view_if_needed()
            active = page.locator("#canonical-active-match").bounding_box()
            self.assertGreater(active["height"], 0)
            self.assertGreaterEqual(active["y"], 0)
            self.assertLess(active["y"], 900)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def source(self, page, response, original, *, count):
        self.assertEqual("".join(native_html.SourceText(response.body().decode()).parts), original)
        self.assertEqual(
            page.locator("#canonical-source-text").text_content(),
            original.replace("\r\n", "\n").replace("\r", "\n"),
        )
        self.assertEqual(page.locator("#canonical-source-text mark").count(), count)
        self.assertEqual(page.locator("#canonical-active-match").count(), 1)
        self.assertEqual(
            page.locator("#canonical-active-match").get_attribute("aria-current"), "true"
        )
        self.assertTrue(page.url.endswith("#canonical-active-match"))
        # This assertion precedes any screenshot scrolling: the actual native
        # form fragment must bring the selected passage into the viewport.
        page.wait_for_function(
            """() => {
              const mark = document.getElementById('canonical-active-match');
              const box = mark && mark.getBoundingClientRect();
              return box && box.height > 0 && box.top >= 0 && box.top < window.innerHeight;
            }""",
            timeout=5000,
        )
        active = page.locator("#canonical-active-match").bounding_box()
        self.assertGreaterEqual(active["y"], 0)
        self.assertLess(active["y"], page.viewport_size["height"])

    def test_native_exact_question_answer_matches_previous_next_and_current_denials(self):
        from playwright.sync_api import sync_playwright

        answer = (
            "  "
            + "فقرة اصطناعية محفوظة قبل المقطع المطلوب.\r\n" * 30
            + "المُعاملاتِ ثم المعاملات\r\n<script>window.privateMatchSentinel=1</script> ثم المُعاملات  "
        )
        self.answer(answer)
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
                self.submit(page, "cs_rebuild")
                self.query(page, "المعاملات", "FTS")
                question_form = page.locator('.canonical-hit[data-kind="QUESTION"] form').first
                response = self.submit(page, "cs_source", form=question_form)
                self.source(page, response, self.question, count=1)
                self.assertEqual(
                    page.locator("#canonical-active-match").text_content(), "المُعاملاتِ"
                )
                self.capture(page, "exact-question-match")
                self.query(page, "المعاملات", "FTS")
                answer_form = page.locator('.canonical-hit[data-kind="ANSWER"] form').first
                response = self.submit(page, "cs_source", form=answer_form)
                self.source(page, response, answer, count=3)
                self.assertEqual(page.evaluate("typeof window.privateMatchSentinel"), "undefined")
                self.assertIn(
                    "الموضع 1 من 3", page.locator("#canonical-match-position").inner_text()
                )
                self.capture(page, "answer-first-match")
                response = self.submit(
                    page, "cs_source", form=page.locator("#canonical-next-match")
                )
                self.source(page, response, answer, count=3)
                self.assertIn(
                    "الموضع 2 من 3", page.locator("#canonical-match-position").inner_text()
                )
                self.capture(page, "answer-second-match")
                response = self.submit(
                    page, "cs_source", form=page.locator("#canonical-next-match")
                )
                self.source(page, response, answer, count=3)
                self.assertIn(
                    "الموضع 3 من 3", page.locator("#canonical-match-position").inner_text()
                )
                self.assertEqual(page.locator("#canonical-next-match").count(), 0)
                response = self.submit(
                    page, "cs_source", form=page.locator("#canonical-previous-match")
                )
                self.source(page, response, answer, count=3)
                self.assertIn(
                    "الموضع 2 من 3", page.locator("#canonical-match-position").inner_text()
                )
                self.capture(page, "answer-previous-match")
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before)
                self.authority.denied.add("SEARCH")
                self.submit(page, "cs_source", form=page.locator("#canonical-next-match"), code=409)
                self.assertNotIn("privateMatchSentinel", page.locator("body").inner_text())
                self.authority.denied.remove("SEARCH")
                page.goto(self.live_server_url + "/casework/staff/")
                self.submit(page, "open")
                self.submit(page, "cs_open")
                self.query(page, "المعاملات", "FTS")
                self.sync(lambda: self.answer("جواب اصطناعي أحدث يجعل نتيجة البحث السابقة قديمة"))
                self.submit(page, "cs_source", code=409)
                self.assertNotIn("privateMatchSentinel", page.locator("body").inner_text())
                self.assertEqual(
                    self.sync(
                        lambda: (
                            CaseSource.objects.get(case_id=self.common["case_id"]).original_question
                        )
                    ),
                    self.question,
                )
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "protected_browser": True,
                            "widths": [320, 1280],
                            "exact_question_match": True,
                            "exact_answer_match": True,
                            "native_previous_and_next": True,
                            "native_fragment_navigation": True,
                            "original_text_bytes_preserved": True,
                            "question_sha256": text_digest(self.question),
                            "answer_sha256": text_digest(answer),
                            "html_source_escaped": True,
                            "stale_source_denied": True,
                            "current_access_revocation": True,
                            "no_navigation_writes": True,
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
