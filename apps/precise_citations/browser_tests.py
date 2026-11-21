"""Protected native composer/reviewer/source/export journey; no local sandbox bypass."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .models import CitationAnchor, CitationReview, CitationSet
from .test_support import FEATURES, CitationFixture

OUT = Path(".local/qa/functional-continuation/citations-browser")


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class PreciseCitationBrowserTests(CitationFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(work).result(timeout=30)

    def submit(self, page, button):
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, 200, page.locator("body").inner_text()[:1000])
        self.assertIn("no-store", response.value.headers.get("cache-control", ""))

    def open_case(self, page, action):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        opener = page.locator(
            f'form:visible:has([name="case_ref"][value="{self.receipt["public_ref"]}"]):has([name="action"][value="open"])'
        ).first
        self.submit(page, opener.locator("button").first)
        target = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(target.count(), 1)
        self.submit(page, target.locator("button").first)

    def login(self, page, subject):
        page.goto(self.live_server_url + "/casework/staff/login/")
        name = {"editor": "editor", "other": "reviewer", "publisher": "publisher"}[subject]
        page.locator("#credential").fill(f"synthetic-{name}-credential-32-characters")
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.assertEqual(response.value.status, 200)

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_exact_phrase_review_original_export_and_withdrawal(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected browser proof requires FATWA_BROWSER_SANDBOX=1")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )

            def page():
                context = browser.new_context(
                    viewport={"width": 320, "height": 900}, accept_downloads=True
                )
                contexts.append(context)

                def route(request):
                    target = urlsplit(request.request.url)
                    if (
                        target.scheme != "http"
                        or target.netloc != urlsplit(self.live_server_url).netloc
                    ):
                        external.append(request.request.url)
                        request.abort()
                    else:
                        request.continue_()

                context.route("**/*", route)
                context.tracing.start(screenshots=True, snapshots=True)
                result = context.new_page()
                result.on("pageerror", lambda error: errors.append(str(error)))
                return result

            try:
                author, reviewer, publisher = page(), page(), page()
                for current, subject in (
                    (author, "editor"),
                    (reviewer, "other"),
                    (publisher, "publisher"),
                ):
                    self.login(current, subject)
                self.open_case(author, "precise_open")
                author.locator("#precise-text").fill(self.answer_text)
                author.locator("#precise-phrase").fill("عبارة محددة")
                self.submit(author, author.locator('button[name="command"][value="find"]'))
                self.assertEqual(author.locator('[name="occurrence"]').count(), 2)
                author.locator('[name="occurrence"]').nth(1).check()
                author.locator("#precise-selection").select_option(
                    "LIBRARY:" + self.material["version_id"]
                )
                author.locator("#precise-mode").select_option("TEXT")
                author.locator("#precise-start").fill("0")
                author.locator("#precise-end").fill("12")
                self.submit(author, author.locator('button[name="command"][value="preview"]'))
                self.assertEqual(author.locator("#precise-text").input_value(), self.answer_text)
                author.locator('[name="occurrence"]').nth(1).check()
                self.submit(author, author.locator('button[name="command"][value="add"]'))
                self.capture(author, "pending")
                author.locator('#precise-compose [name="confirmed"]').check()
                self.submit(author, author.locator('button[name="command"][value="save"]'))
                identifier = author.locator("[data-citation-set]").get_attribute(
                    "data-citation-set"
                )
                source_url = author.locator("[data-citation-anchor] a").first.get_attribute("href")
                self.open_case(reviewer, "precise_open")
                reviewer.locator("#precise-review-note").fill("مراجعة بشرية مستقلة للنسخة والموضع")
                reviewer.locator('#precise-review [name="confirmed"]').check()
                self.submit(reviewer, reviewer.locator('#precise-review button[value="APPROVE"]'))
                self.capture(reviewer, "reviewed")
                self.assertEqual(author.goto(self.live_server_url + source_url).status, 200)
                self.assertEqual(author.locator("#cited-position").inner_text(), "مصدر اصطناعي")
                self.capture(author, "exact-source")
                with author.expect_response(
                    lambda response: response.url.endswith(source_url + "file/")
                ) as original:
                    self.submit(
                        author,
                        author.get_by_role(
                            "link", name="فتح الأصل الموثق بالحقوق الحالية", exact=True
                        ),
                    )
                self.assertEqual(
                    original.value.headers["content-type"], "text/plain; charset=utf-8"
                )
                self.assertEqual(original.value.body(), "مصدر اصطناعي دقيق محفوظ للإحالة".encode())
                self.assertIn(
                    "مصدر اصطناعي دقيق محفوظ للإحالة", author.locator("body").inner_text()
                )
                self.open_case(author, "precise_open")
                with author.expect_download() as downloading:
                    author.get_by_role("link", name="تنزيل مرجع الإحالات", exact=True).click()
                target = OUT / "citations.json"
                downloading.value.save_as(str(target))
                exported = json.loads(target.read_text())
                self.assertEqual(
                    exported["citations"][0]["start"], self.answer_text.rindex("عبارة محددة")
                )
                self.assertNotIn("case_id", target.read_text())
                self.submit(
                    author, author.get_by_role("link", name="نسخة مقروءة للطباعة", exact=True)
                )
                self.assertIn("محارف المصدر 1–12", author.locator("main").inner_text())
                self.capture(author, "print")
                self.open_case(publisher, "rl_open")
                self.submit(
                    publisher, publisher.get_by_role("button", name="فتح المادة ونسخها", exact=True)
                )
                withdrawal = publisher.locator('form.library-decision[data-command="WITHDRAW"]')
                withdrawal.locator('[name="note"]').fill("سحب المصدر للتحقق من الإحالات")
                withdrawal.locator('[name="confirmed"]').check()
                self.submit(publisher, withdrawal.locator("button").first)
                response = author.goto(self.live_server_url + source_url)
                self.assertEqual(response.status, 404)
                self.assertNotIn("مصدر اصطناعي", author.locator("body").inner_text())
                counts = self.sync(
                    lambda: (
                        CitationSet.objects.count(),
                        CitationAnchor.objects.count(),
                        CitationReview.objects.count(),
                    )
                )
                self.assertEqual(counts, (1, 1, 1))
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"actor-{index}-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "case_ref": self.receipt["public_ref"],
                            "citation_set": identifier,
                            "checks": [
                                "native literal second occurrence",
                                "unsaved text retained",
                                "independent review",
                                "exact source text and original bytes",
                                "native reference print and download",
                                "native source withdrawal",
                            ],
                            "console_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for context in contexts:
                    context.close()
                browser.close()
