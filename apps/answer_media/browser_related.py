"""Protected actual editor: source side panel preserves unsaved bytes and fields."""

import json
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings
from django.utils.html import escape

from apps.canonical_search import browser_tests as browser_helpers
from apps.casework.models import CaseEvent

from .models import AnswerPart
from .related_test_support import CREDENTIAL, FEATURES, RelatedFixture
from .test_youtube import LINK

OUT = Path(".local/qa/functional-continuation/answer-related-browser")
DRAFT = "مسودة بشرية غير محفوظة، تبقى كما كتبتها.\nالسطر الثاني مستقل عن نتيجة البحث."
UPLOAD = b"synthetic human attachment retained in the real file input\n"


@override_settings(**FEATURES)
class RelatedMaterialBrowserTests(RelatedFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_helpers.CanonicalSearchBrowserTests.sync
    form = browser_helpers.CanonicalSearchBrowserTests.form
    submit = browser_helpers.CanonicalSearchBrowserTests.submit

    def panel_submit(self, page, action, *, code=200):
        form = self.form(page, "answer_media_related_" + action)
        button = form.locator("button").first
        button.wait_for()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/casework/staff/"
            )
        ) as request:
            button.focus()
            button.press("Enter")
        self.assertEqual(request.value.status, code)
        self.assertIn("no-store", request.value.headers.get("cache-control", ""))
        page.wait_for_function(
            "document.querySelector('#answer-related-panel').getAttribute('aria-busy') !== 'true'"
        )
        return request.value

    def preserved(self, page, textarea, file_input, event_count):
        self.assertTrue(textarea.evaluate("node => node.isConnected"))
        self.assertTrue(file_input.evaluate("node => node.isConnected"))
        self.assertEqual(page.locator("#multipart-text").input_value(), DRAFT)
        self.assertEqual(page.locator("#youtube-url").input_value(), LINK["url"])
        self.assertEqual(page.locator("#youtube-label").input_value(), LINK["label"])
        selected = page.locator("#answer-file").evaluate(
            """async input => {
              const file = input.files[0];
              const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
              return {name: file.name, size: file.size,
                sha256: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')};
            }"""
        )
        self.assertEqual(
            selected,
            {"name": "human-draft.txt", "size": len(UPLOAD), "sha256": sha256(UPLOAD).hexdigest()},
        )
        self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), event_count)

    def capture(self, page, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            if width == 1280:
                panel = page.locator("#answer-related-panel").bounding_box()
                editor = page.locator('[aria-label="مسودة الجواب المستقلة"]').bounding_box()
                self.assertGreaterEqual(panel["x"], editor["x"] + editor["width"])
            filename = f"{name}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_actual_side_panel_preserves_draft_file_and_link_until_explicit_save(self):
        from playwright.sync_api import sync_playwright

        before = CaseEvent.objects.count()
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "external_requests": [],
            "page_errors": [],
        }
        origin = urlsplit(self.live_server_url).netloc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            def local(route):
                url = urlsplit(route.request.url)
                if url.scheme != "http" or url.netloc != origin:
                    proof["external_requests"].append("blocked")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local)
            page = context.new_page()
            page.on("pageerror", lambda error: proof["page_errors"].append(type(error).__name__))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(CREDENTIAL)
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.submit(page, "answer_media")
                page.locator("#multipart-text").fill(DRAFT)
                page.locator("#answer-file").set_input_files(
                    {"name": "human-draft.txt", "mimeType": "text/plain", "buffer": UPLOAD}
                )
                page.locator("#youtube-url").fill(LINK["url"])
                page.locator("#youtube-label").fill(LINK["label"])
                textarea = page.locator("#multipart-text").element_handle()
                file_input = page.locator("#answer-file").element_handle()
                page.locator("#related-query").fill("المعاملات المالية")
                self.panel_submit(page, "search")
                self.assertEqual(page.locator(".related-results article").count(), 2)
                self.preserved(page, textarea, file_input, before)
                self.capture(page, "separate-current-results", proof)
                source_response = self.panel_submit(page, "open")
                self.assertIn(escape(self.question).encode(), source_response.body())
                self.assertEqual(
                    page.locator("#related-source-text").text_content(),
                    self.question.replace("\r\n", "\n").replace("\r", "\n"),
                )
                self.preserved(page, textarea, file_input, before)
                self.capture(page, "exact-source-with-unsaved-draft", proof)
                self.panel_submit(page, "back")
                self.preserved(page, textarea, file_input, before)
                self.panel_submit(page, "open")
                self.authority.denied.add("SEARCH")
                self.panel_submit(page, "back", code=409)
                self.assertEqual(page.locator(".related-results,.related-opened").count(), 0)
                self.assertIn(
                    "بقيت مسودتك",
                    page.locator('#answer-related-panel [role="status"]').inner_text(),
                )
                self.preserved(page, textarea, file_input, before)
                self.capture(page, "revoked-source-cleared-draft-retained", proof)
                self.authority.denied.clear()
                page.locator('[name="synthetic_only"]').check()
                self.submit(page, "answer_media_save")
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before + 1)

                def saved():
                    rows = list(AnswerPart.objects.order_by("ordinal"))
                    return [(row.kind, bytes(row.original), row.sha256) for row in rows]

                self.assertEqual(
                    self.sync(saved),
                    [
                        ("TEXT", DRAFT.encode(), sha256(DRAFT.encode()).hexdigest()),
                        ("FILE", UPLOAD, sha256(UPLOAD).hexdigest()),
                        (
                            "YOUTUBE_LINK",
                            LINK["url"].encode(),
                            sha256(LINK["url"].encode()).hexdigest(),
                        ),
                    ],
                )
                self.assertEqual(proof["external_requests"], [])
                self.assertEqual(proof["page_errors"], [])
                proof.update(
                    status="PASS",
                    separate_side_panel=True,
                    exact_current_source=True,
                    same_draft_and_file_dom=True,
                    exact_selected_file_hash=True,
                    unsaved_link_preserved=True,
                    no_case_write_during_panel_reads=True,
                    revoked_source_cleared=True,
                    explicit_save_once=True,
                )
                (OUT / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
