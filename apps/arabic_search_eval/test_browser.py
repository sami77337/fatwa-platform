"""Synthetic Chrome journey: pages/open/back then independent review identities."""

import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.research_workspace import test_browser as old_browser
from apps.research_workspace.tests import SETTINGS
from apps.source_rights.tests import Authority as SourceAuthority

from . import test_services as fixtures
from .models import EvaluationDecision
from .test_review import ReviewFixture
from .test_v14_batch import large_fixture


@override_settings(
    **SETTINGS, FATWA_SOURCE_RIGHTS_ENABLED=True, FATWA_ARABIC_SEARCH_EVAL_ENABLED=True
)
class SearchReviewBrowser(ReviewFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = old_browser.ResearchBrowserTests.sync
    click = old_browser.ResearchBrowserTests.click
    grant = fixtures.AdapterTests.grant

    def setUp(self):
        with patch("apps.knowledge_links.tests.source_fixture", side_effect=large_fixture):
            super().setUp()
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=SourceAuthority(self.receipt["public_ref"]),
        )
        configured.enable()
        self.addCleanup(configured.disable)
        for i in range(2, 26):
            self.grant(i)

    def test_pages_roundtrip_and_pending_independent_review_on_mobile_keyboard(self):
        from playwright.sync_api import sync_playwright

        out = Path("apps/arabic_search_eval/evidence/browser")
        out.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
                args=["--disable-dev-shm-usage"],
            )
            external = []

            def context():
                ctx = browser.new_context(viewport={"width": 320, "height": 900})

                def route(r):
                    if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(r.request.url)
                        r.abort()
                    else:
                        r.continue_()

                ctx.route("**/*", route)
                return ctx

            def login(ctx, credential):
                page = ctx.new_page()
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(credential)
                self.click(page, "دخول المكتب")
                self.click(page, "البحث في مصادر القضية")
                return page

            try:
                editor = context()
                page = login(editor, "synthetic-editor-credential-32-characters")
                page.locator("#kind").select_option("REFERENCE")
                page.locator("#edition").select_option(str(self.catalog_id))
                page.locator("#query").fill("عنوان")
                self.click(page, "تجربة بحث العناوين بالكلمات الكاملة")
                self.click(page, "الصفحة التالية")
                self.assertEqual(page.locator("article[data-resource-id]").count(), 4)
                self.click(page, "فتح المصدر: عنوان رقم 25")
                self.click(page, "العودة إلى نتائج البحث نفسها")
                self.assertIn("الصفحة 2", page.locator("#research-ranking-scope").inner_text())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(out / f"page2-{width}.png"))
                self.click(page, "إصدارات تقييم البحث والمراجعة البشرية")
                page.get_by_text("اقتراح إصدار جديد مع حفظ التاريخ", exact=True).click()
                page.locator("#bundle").fill(json.dumps(self.bundle, ensure_ascii=False))
                page.locator("#proposal_note").fill(
                    "Synthetic browser proposal, no real human review"
                )
                self.click(page, "حفظ إصدار ينتظر المراجعة")
                self.assertIn("بانتظار المراجعة", page.locator("main").inner_text())
                self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 0)
                reviewer = context()
                page = login(reviewer, "synthetic-publisher-credential-32-characters")
                self.click(page, "إصدارات تقييم البحث والمراجعة البشرية")
                for i in range(2):
                    page.locator(f"#verdict_{i}").select_option("AGREE")
                    page.locator(f"#note_{i}").fill("Synthetic test judgement, not human gold")
                page.locator("#decision_note").fill("Synthetic browser test decision only")
                page.locator("input[name=confirm]").check()
                self.click(page, "اعتماد هذه النسخة فقط")
                self.assertIn("اعتمده المراجع المسجل", page.locator("main").inner_text())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(out / f"review-{width}.png"))
                self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 1)
                self.assertEqual(external, [])
            finally:
                browser.close()
