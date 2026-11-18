"""Synthetic native-form browser journey; no external requests or real identities."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from tests.casework.test_http import WEB_SETTINGS

from .tests import FEATURES, Fixture


@override_settings(
    **{**WEB_SETTINGS, **FEATURES, "ROOT_URLCONF": "apps.classification_review.urls"}
)
class ClassificationBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_native_propose_independent_review_withdraw_rtl(self):
        from playwright.sync_api import sync_playwright

        original = self.directory.authenticate
        self.directory.authenticate = lambda credential: (
            self.directory.resolve("publisher")
            if credential == "synthetic-classification-reviewer"
            else original(credential)
        )
        errors, external, observations = [], [], []
        sandbox = os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1"
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True, chromium_sandbox=sandbox
            )
            try:

                def enter(page, credential):
                    page.goto(self.live_server_url + "/casework/staff/login/")
                    page.locator('[name="credential"]').fill(credential)
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                    with page.expect_navigation():
                        page.evaluate(
                            """fields => {
                            const f=document.createElement('form'); f.method='POST'; f.action='/casework/staff/';
                            fields.csrfmiddlewaretoken=document.querySelector('[name=csrfmiddlewaretoken]').value;
                            for(const [name,value] of Object.entries(fields)) {
                              const i=document.createElement('input');i.name=name;i.value=value;f.appendChild(i);
                            }
                            document.body.appendChild(f);f.submit();
                        }""",
                            {"action": "classification_desk", "publication_id": self.edition["id"]},
                        )

                for width in (320, 1280):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "request",
                        lambda request: (
                            external.append(request.url)
                            if urlsplit(request.url).netloc != urlsplit(self.live_server_url).netloc
                            else None
                        ),
                    )
                    enter(page, "synthetic-editor-credential-32-characters")
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    page.locator("#new-label").fill(f"تصنيف اصطناعي {width}")
                    page.locator("#new-reason").fill("سبب اصطناعي موثق من بيانات الفهرس فقط")
                    page.get_by_role("button", name="حفظ اقتراح غير معتمد", exact=True).click()
                    article = page.locator("article").filter(has_text=f"تصنيف اصطناعي {width}")
                    self.assertIn("PROPOSED", article.inner_text())
                    self.assertIn("لا قرار بشري حتى الآن", article.inner_text())
                    article.locator("details").first.locator("summary").click()
                    self.assertIn("الصفحة المطبوعة", article.inner_text())
                    page.keyboard.press("Tab")
                    self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    Path("/tmp/v13-classification-browser").mkdir(exist_ok=True)
                    page.screenshot(
                        path=f"/tmp/v13-classification-browser/rtl-{width}.png", full_page=True
                    )
                    enter(page, "synthetic-classification-reviewer")
                    article = page.locator("article").filter(has_text=f"تصنيف اصطناعي {width}")
                    article.locator('textarea[name="note"]').fill("مراجعة بشرية اصطناعية مستقلة")
                    article.locator('[name="confirm"]').check()
                    article.get_by_role(
                        "button", name="اعتماد التصنيف التجريبي", exact=True
                    ).click()
                    article = page.locator("article").filter(has_text=f"تصنيف اصطناعي {width}")
                    self.assertIn("APPROVED", article.inner_text())
                    article.locator('textarea[name="note"]').fill("سحب القرار الاصطناعي")
                    article.locator('[name="confirm"]').check()
                    article.get_by_role("button", name="سحب الاقتراح أو القرار", exact=True).click()
                    self.assertIn("WITHDRAWN", page.locator("main").inner_text())
                    self.assertNotIn("سبب اصطناعي موثق", page.content())
                    observations.append(
                        {
                            "width": width,
                            "rtl": True,
                            "overflow": False,
                            "native_propose_review_withdraw": True,
                        }
                    )
                    page.context.close()
                Path("/tmp/v13-classification-browser/result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "results": observations,
                            "external_requests": external,
                            "page_errors": errors,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
