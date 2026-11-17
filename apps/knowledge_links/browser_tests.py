"""Browser evidence for the isolated app's authorized browse/open/return UI."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from tests.casework.test_http import WEB_SETTINGS

from .tests import FEATURES, Fixture


@override_settings(**{**WEB_SETTINGS, **FEATURES, "ROOT_URLCONF": "apps.knowledge_links.urls"})
class KnowledgeBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_rtl_reference_transcript_return_and_private_boundary(self):
        from playwright.sync_api import sync_playwright

        reference, transcript = self.propose(), self.propose("TRANSCRIPT")
        self.approve(reference)
        self.approve(transcript)
        errors, external, results = [], [], []
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
            )
            try:
                for width in (320, 1280):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.on("pageerror", lambda err: errors.append(str(err)))
                    page.on(
                        "request",
                        lambda req: (
                            external.append(req.url)
                            if urlsplit(req.url).netloc != urlsplit(self.live_server_url).netloc
                            else None
                        ),
                    )
                    page.goto(self.live_server_url + "/casework/staff/login/")
                    page.locator('[name="credential"]').fill(
                        "synthetic-editor-credential-32-characters"
                    )
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                    # Shared navigation is integrator-owned; submit its documented
                    # entry contract once, then use this app's actual native forms.
                    with page.expect_navigation():
                        page.evaluate(
                            """fields => {
                          const f=document.createElement('form'); f.method='POST'; f.action='/casework/staff/';
                          fields.csrfmiddlewaretoken=document.querySelector('[name=csrfmiddlewaretoken]').value;
                          for (const [name,value] of Object.entries(fields)) {const i=document.createElement('input');i.name=name;i.value=value;f.appendChild(i);}
                          document.body.appendChild(f);f.submit();
                        }""",
                            {
                                "action": "knowledge_browse",
                                "publication_id": self.edition["id"],
                                "query": "فرع",
                            },
                        )
                    self.assertNotIn("PRIVATE", page.content())
                    self.assertNotIn(self.receipt["public_ref"], page.content())
                    self.assertNotIn(self.transcript_text, page.content())
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    page.get_by_role("button", name="فتح المادة المصرح بها", exact=True).click()
                    self.assertIn("الصفحة المطبوعة", page.content())
                    page.get_by_role(
                        "button", name="العودة إلى العلاقات وموضع البحث السابق", exact=True
                    ).click()
                    self.assertEqual(page.locator("#knowledge-query").input_value(), "فرع")
                    page.locator("#knowledge-query").fill("")
                    page.get_by_role("button", name="بحث", exact=True).click()
                    page.locator("article").filter(has_text="سؤال من درس").get_by_role(
                        "button", name="فتح المادة المصرح بها"
                    ).click()
                    self.assertIn(
                        self.transcript_text.strip(), page.locator("blockquote").inner_text()
                    )
                    page.get_by_role(
                        "button", name="العودة إلى العلاقات وموضع البحث السابق", exact=True
                    ).click()
                    self.assertEqual(page.locator("#knowledge-query").input_value(), "")
                    self.assertNotIn(self.transcript_text, page.content())
                    page.keyboard.press("Tab")
                    self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    self.assertFalse(overflow)
                    results.append(
                        {
                            "width": width,
                            "rtl": True,
                            "return_query_preserved": True,
                            "overflow": overflow,
                        }
                    )
                    page.context.close()
                output = Path(".local/qa/knowledge-links")
                output.mkdir(parents=True, exist_ok=True)
                (output / "browser.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
                            "results": results,
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
