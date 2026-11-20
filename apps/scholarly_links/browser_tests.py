"""Protected browser proof of the connected native lesson/relationship workflow."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .models import CaseLessonLink, CaseRelation, Lesson, LinkDecision
from .tests import HTTP_FEATURES, Fixture

OUT = Path(".local/qa/functional-completion/scholarly-browser")


@override_settings(**HTTP_FEATURES)
class ScholarlyBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as workers:
            return workers.submit(work).result(timeout=30)

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.press("Enter")
        self.assertIsNotNone(navigation.value)
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def form(self, page, action, container=None):
        host = container or page
        form = host.locator(f'form:visible:has([name="action"][value="{action}"])')
        self.assertEqual(form.count(), 1, f"ambiguous visible native action: {action}")
        return form

    def send(self, page, form):
        self.submit(page, form.locator('button:visible:not([type="button"])'))

    def review_last(self, page, kind):
        article = page.locator(f'article[data-link-kind="{kind}"]').last
        form = self.form(page, "scholarly_review", article)
        form.locator('[name="transition"]').select_option("APPROVE")
        form.locator('[name="note"]').fill("مراجعة بشرية اصطناعية للعلاقة والنسخة المقصودة")
        self.send(page, form)

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)
            proof["screenshots"].append(f"{label}-{width}.png")

    def test_native_series_lessons_typed_links_review_and_filters(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "external_requests": [],
            "page_errors": [],
            "owner_points": [74, 175, 176, 177, 178, 181, 182, 183, 185, 186, 226, 228],
        }
        before = self.snapshot()
        origin = self.live_server_url
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    context = browser.new_context(viewport={"width": 320, "height": 780})
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)

                    def local_only(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                            proof["external_requests"].append("blocked")
                            route.abort()
                        else:
                            route.continue_()

                    context.route("**/*", local_only)
                    page = context.new_page()
                    page.on(
                        "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                    )
                    page.goto(origin + "/casework/staff/login/")
                    page.locator("#credential").fill(self.directory.credentials["mufti-a"])
                    self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))
                    self.submit(
                        page,
                        page.get_by_role("button", name=self.receipt["public_ref"], exact=True),
                    )
                    self.send(page, self.form(page, "scholarly_open"))
                    self.assertEqual(
                        page.locator("#scholarly-case-reference").inner_text(),
                        self.receipt["public_ref"],
                    )
                    page.locator("#lesson-category-label").fill("قراءة المتون — تصنيف مستقل للدروس")
                    self.send(page, self.form(page, "lesson_category_create"))
                    page.locator("#series-title").fill("سلسلة قراءة اصطناعية")
                    page.locator("#series-teachers").fill("معلم اصطناعي صرّح بنسبة المادة إليه")
                    page.locator("#series-teacher-is-me").select_option("yes")
                    self.send(page, self.form(page, "lesson_series_save"))
                    series_id = page.locator("article[data-series-id]").get_attribute(
                        "data-series-id"
                    )
                    for title in ("الدرس الأول المحفوظ", "الدرس الثاني المحفوظ"):
                        form = page.locator(f'form[data-create-lesson="{series_id}"]')
                        form.locator('[name="title"]').fill(title)
                        form.locator('[name="source_part_id"]').select_option(index=1)
                        form.locator('[name="provenance"]').fill(
                            "اختيار بشري صريح لملف المصدر الاصطناعي ونسبته"
                        )
                        self.send(page, form)
                    first_id = page.locator("li[data-lesson-id]").first.get_attribute(
                        "data-lesson-id"
                    )
                    second_id = page.locator("li[data-lesson-id]").last.get_attribute(
                        "data-lesson-id"
                    )
                    for index in (0, 1):
                        page.locator("#lesson-link-target").select_option(index=index)
                        self.assertEqual(page.locator("#lesson-start").input_value(), "")
                        if index == 0:
                            page.locator("#lesson-start").fill("10")
                            page.locator("#lesson-end").fill("50")
                        page.locator("#lesson-link-reason").fill(
                            "تناول هذه المسألة في الدرس المختار؛ ليس اقتراحًا آليًا"
                        )
                        self.send(page, self.form(page, "lesson_link_propose"))
                        self.review_last(page, "LESSON")
                    form = self.form(
                        page, "lesson_move", page.locator(f'li[data-lesson-id="{second_id}"]')
                    )
                    form.locator('[name="direction"]').select_option("up")
                    self.send(page, form)
                    self.assertEqual(
                        page.locator("li[data-lesson-id]").first.get_attribute("data-lesson-id"),
                        second_id,
                    )
                    for kind in ("RELATED", "REFERRED_BY_SHEIKH", "DUPLICATE_OF", "SUPERSEDES"):
                        option = (
                            page.locator("#relation-target option")
                            .filter(has_text=self.receipts[1]["public_ref"])
                            .first
                        )
                        page.locator("#relation-target").select_option(
                            option.get_attribute("value")
                        )
                        page.locator("#relation-kind").select_option(kind)
                        page.locator("#relation-reason").fill(
                            "اختيار بشري لنوع العلاقة واتجاهها ونسخة الجواب"
                        )
                        self.send(page, self.form(page, "relation_propose"))
                        self.review_last(page, "RELATION")
                    self.capture(page, "lessons-and-relations", proof)
                    self.send(page, self.form(page, "scholarly_search_open"))
                    page.locator("#scholarly-query").fill("alpha")
                    page.locator("#scholarly-lesson").select_option(first_id)
                    page.locator("#scholarly-relation").select_option("REFERRED_BY_SHEIKH")
                    self.send(page, self.form(page, "scholarly_search"))
                    self.assertIn("1", page.locator("#scholarly-result-count").inner_text())
                    self.assertEqual(page.locator("article[data-case-ref]").count(), 1)
                    self.capture(page, "filtered-research", proof)
                    self.send(page, self.form(page, "scholarly_search_open"))
                    self.assertEqual(page.locator("#scholarly-query").input_value(), "")
                    self.assertEqual(page.locator("#scholarly-lesson").input_value(), "")
                    self.assertEqual(page.locator("#scholarly-relation").input_value(), "")
                    self.assertEqual(page.locator("article[data-case-ref]").count(), 3)
                    page.locator("#scholarly-related-case").select_option(
                        self.receipt["public_ref"]
                    )
                    page.locator("#scholarly-relation").select_option("REFERRED_BY_SHEIKH")
                    self.send(page, self.form(page, "scholarly_search"))
                    self.assertEqual(
                        page.locator("article[data-case-ref]").get_attribute("data-case-ref"),
                        self.receipts[1]["public_ref"],
                    )
                    self.send(
                        page,
                        self.form(page, "scholarly_open", page.locator("article[data-case-ref]")),
                    )
                    self.assertEqual(
                        page.locator("#scholarly-case-reference").inner_text(),
                        self.receipts[1]["public_ref"],
                    )
                    self.assertIn("إحالة واردة إلى هذه القضية", page.locator("main").inner_text())
                    self.assertEqual(self.sync(self.snapshot), before)
                    self.assertEqual(
                        self.sync(
                            lambda: (
                                Lesson.objects.count(),
                                CaseLessonLink.objects.count(),
                                CaseRelation.objects.count(),
                                LinkDecision.objects.filter(action="APPROVE").count(),
                            )
                        ),
                        (2, 2, 4, 6),
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof["status"] = "PASS"
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                    context.close()
                finally:
                    browser.close()
        finally:
            (OUT / "result.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
