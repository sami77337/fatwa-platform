"""Real Chromium proof of multiple-source selection without losing unsaved text."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework import services as cases
from tests.casework.test_http import WEB_SETTINGS, Directory

from .tests import source_fixture

OUT = Path(".local/qa/v8-citations/browser")


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "apps.case_citations.urls",
        "FATWA_CASE_CITATIONS_ENABLED": True,
    }
)
class MultiCitationBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_native_multiple_citations_preserve_draft_and_full_list_mobile_desktop(self):
        from playwright.sync_api import sync_playwright

        edition = source_fixture()
        receipt = cases.intake_case(
            original_question="سؤال اصطناعي لمحرر الإحالات",
            source_event_id="browser-citations",
            requester_id="browser-requester",
            idempotency_key="browser-multi",
            synthetic_fixtures_only=True,
        )
        directory = Directory()
        directory.grant(receipt["public_ref"])
        errors, external = [], []
        OUT.mkdir(parents=True, exist_ok=True)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory), sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(r):
                    if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(r.request.url)
                        r.abort()
                    else:
                        r.continue_()

                page.route("**/*", route)

                def click(name):
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        page.get_by_role("button", name=name, exact=True).click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertIn("no-store", navigation.value.headers["cache-control"])

                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(directory.credential)
                click("دخول المكتب")
                click(receipt["public_ref"])
                click("تحرير جواب بإحالة موثقة")
                draft = "مسودة بشرية محفوظة أثناء البحث\nمع سطر ثانٍ."
                page.locator("#answer").fill(draft)
                page.locator("#edition").select_option(str(edition))
                page.locator("#part").fill("مقدمة")
                page.locator("#page").fill("2")
                click("البحث مع الاحتفاظ بالمسودة")
                self.assertEqual(page.locator("#answer").input_value(), draft)
                page.locator("#note").fill("تعليق الموضع الأول")
                click("إضافة الموضع 2 إلى القائمة")
                page.locator("#page").fill("3")
                click("البحث مع الاحتفاظ بالمسودة")
                page.locator("#note").fill("تعليق الموضع الثاني")
                click("إضافة الموضع 3 إلى القائمة")
                self.assertEqual(page.locator("#answer").input_value(), draft)
                self.assertIn("(2/12)", page.content())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(OUT / f"complete-list-{width}.png"), full_page=True)
                page.locator('[name="confirm"]').check()
                click("حفظ الجواب والقائمة الكاملة")
                self.assertIn("حُفظ إصدار جواب جديد بكل الإحالات المعروضة", page.content())
                self.assertEqual(page.locator("#answer").input_value(), draft)
                click("العودة إلى القضية دون حفظ هذه المسودة")
                click("تحرير جواب بإحالة موثقة")
                self.assertEqual(page.locator("#answer").input_value(), draft)
                self.assertIn("(2/12)", page.content())
                self.assertIn("تعليق الموضع الأول", page.content())
                self.assertIn("تعليق الموضع الثاني", page.content())
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        dict(
                            result="PASS",
                            browser=browser.version,
                            sandbox=sandbox,
                            widths=[320, 1280],
                            citations=2,
                            page_errors=errors,
                            external_requests=external,
                        ),
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            finally:
                browser.close()
