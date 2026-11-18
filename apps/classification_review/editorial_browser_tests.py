"""Synthetic native V14 flow under enforced rights and maintenance admission."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from tests.casework.test_http import WEB_SETTINGS

from .editorial_tests import EditorialFixture
from .tests import FEATURES


@override_settings(
    **{
        **WEB_SETTINGS,
        **FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "MIDDLEWARE": [
            "apps.platform_recovery.middleware.MaintenanceGuard",
            *WEB_SETTINGS["MIDDLEWARE"],
        ],
    }
)
class EditorialBrowserTests(EditorialFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_native_classification_to_independent_editorial_publication(self):
        from playwright.sync_api import sync_playwright

        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-independent-publisher-32-characters": "other",
            }.get(credential, "missing")
        )
        errors, external, observations = [], [], []
        sandbox = os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1"
        artifacts = Path("/tmp/v14-classification-browser")
        artifacts.mkdir(exist_ok=True)
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True, chromium_sandbox=sandbox
            )
            try:
                page = browser.new_page(viewport={"width": 320, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if urlsplit(request.url).netloc != urlsplit(self.live_server_url).netloc
                        else None
                    ),
                )

                def enter(credential, fields):
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
                            fields,
                        )

                enter(
                    "synthetic-editor-credential-32-characters",
                    {"action": "classification_desk", "publication_id": self.edition["id"]},
                )
                form = page.locator("form").filter(
                    has=page.get_by_role(
                        "button", name="محاكاة إعداد نسخة تحريرية جديدة", exact=True
                    )
                )
                form.locator('[name="confirm"]').check()
                form.get_by_role("button").click()
                self.assertIn("CANDIDATE", page.locator("main").inner_text())
                self.assertIn("التصنيف التجريبي المنقول", page.locator("main").inner_text())
                binding_id = page.locator('[name="binding_id"]').first.input_value()
                page.locator("details summary").click()
                self.assertIn("الصفحة المطبوعة", page.content())
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                page.keyboard.press("Tab")
                self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                page.screenshot(path=str(artifacts / "candidate-320.png"), full_page=True)
                page.locator('[name="confirm"]').check()
                page.get_by_role(
                    "button", name="تسجيل مراجعة التحرير والخصوصية", exact=True
                ).click()
                self.assertIn("REVIEWED", page.locator("main").inner_text())
                self.assertEqual(
                    page.get_by_role(
                        "button", name="موافقة نشر مستقلة في المحاكاة", exact=True
                    ).count(),
                    0,
                )
                enter(
                    "synthetic-independent-publisher-32-characters",
                    {
                        "action": "classification_editorial_inspect",
                        "publication_id": self.edition["id"],
                        "binding_id": binding_id,
                    },
                )
                page.locator('[name="confirm"]').check()
                page.get_by_role("button", name="موافقة نشر مستقلة في المحاكاة", exact=True).click()
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertIn("PUBLISHED", page.locator("main").inner_text())
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    page.screenshot(path=str(artifacts / f"published-{width}.png"), full_page=True)
                    observations.append({"width": width, "rtl": True, "overflow": False})
                page.get_by_role("button", name="تاريخ التصنيف الأصلي المختصر", exact=True).click()
                self.assertIn("APPROVE", page.locator("main").inner_text())
                self.assertNotIn("PRIVATE classification reason", page.content())
                (artifacts / "result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "results": observations,
                            "native_prepare_review_approve": True,
                            "strict_rights": True,
                            "maintenance_required": True,
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
