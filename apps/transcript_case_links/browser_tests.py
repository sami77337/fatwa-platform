"""Real Chromium: scoped staff uploads, confirms, reopens durable transcript evidence."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision, CaseEvidence
from tests.casework.test_http import Directory

from .models import TranscriptLink
from .tests import new_case


@override_settings(FATWA_CASEWORK_WEB_ENABLED=True)
class BindingBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_staff_preview_confirm_reopen_mobile_desktop_and_other_case_isolation(self):
        from playwright.sync_api import sync_playwright

        mobile, desktop, isolated = new_case(), new_case(), new_case()
        directory = Directory()
        directory.grant(mobile["public_ref"], desktop["public_ref"])
        output = Path(".local/qa/transcript-case-binding")
        output.mkdir(parents=True, exist_ok=True)
        errors, unexpected, results = [], [], []
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
                )
                try:
                    for receipt, width, height in ((mobile, 320, 780), (desktop, 1280, 900)):
                        context = browser.new_context(viewport={"width": width, "height": height})
                        page = context.new_page()
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on(
                            "request",
                            lambda request: (
                                unexpected.append(request.url)
                                if urlsplit(request.url).netloc
                                != urlsplit(self.live_server_url).netloc
                                else None
                            ),
                        )

                        def click(name):
                            with page.expect_navigation(
                                wait_until="domcontentloaded"
                            ) as navigation:
                                page.get_by_role("button", name=name, exact=True).click()
                            self.assertEqual(navigation.value.status, 200)

                        page.goto(self.live_server_url + "/casework/staff/login/")
                        page.locator('[name="credential"]').fill(directory.credential)
                        click("دخول المكتب")
                        click("ربط التفريغات بالقضايا")
                        self.assertNotIn(isolated["public_ref"], page.content())
                        page.locator("#case").select_option(receipt["public_ref"])
                        click("عرض تفريغات القضية")
                        with page.expect_download() as download:
                            page.get_by_role(
                                "button", name="تنزيل حزمة اصطناعية للتجربة", exact=True
                            ).click()
                        path = output / f"synthetic-{width}.zip"
                        download.value.save_as(path)
                        page.locator("#bundle").set_input_files(str(path))
                        page.locator('[name="synthetic_only"]').check()
                        click("حفظ المصدر ومعاينة أسئلته")
                        self.assertIn("معاينة قبل الربط", page.content())
                        page.locator('[name="confirm"]').check()
                        click("ربط السؤال بالقضية")
                        self.assertIn("الروابط المحفوظة (1)", page.content())
                        # A second read comes from PostgreSQL, not hidden preview data.
                        click("عرض تفريغات القضية")
                        self.assertIn("الروابط المحفوظة (1)", page.content())
                        self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                        self.assertTrue(
                            page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        )
                        page.screenshot(path=str(output / f"linked-{width}.png"), full_page=True)
                        results.append({"viewport": [width, height], "status": "PASS"})
                        context.close()
                    version = browser.version
                finally:
                    browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(unexpected, [])
        self.assertEqual(TranscriptLink.objects.count(), 2)
        self.assertEqual(CaseEvidence.objects.filter(case_id=isolated["case_id"]).count(), 1)
        self.assertEqual(AnswerRevision.objects.count(), 0)
        result = {
            "status": "PASS",
            "browser": version,
            "viewports": results,
            "case_binding": "DURABLE_SYNTHETIC",
            "page_errors": 0,
            "external_requests": 0,
        }
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
