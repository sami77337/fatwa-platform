"""Real Chromium journey for V9 source preview, proposals and correction history."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework import services as cases
from tests.casework.test_http import WEB_SETTINGS, Directory

from .models import CitationCorrection
from .tests import source_fixture

OUT = Path(".local/qa/v9-research/browser")


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "apps.case_citations.urls",
        "FATWA_CASE_CITATIONS_ENABLED": True,
    }
)
class ResearchBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_preview_return_proposals_order_correction_and_history(self):
        from playwright.sync_api import sync_playwright

        edition = source_fixture()
        receipt = cases.intake_case(
            original_question="سؤال اصطناعي لمساحة البحث",
            source_event_id="v9-research-browser",
            requester_id="v9-research-browser",
            idempotency_key="v9-research-browser",
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

                def click(name, keyboard=False):
                    button = page.get_by_role("button", name=name, exact=True)
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        if keyboard:
                            button.focus()
                            button.press("Enter")
                        else:
                            button.click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertIn("no-store", navigation.value.headers["cache-control"])

                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(directory.credential)
                click("دخول المكتب")
                click(receipt["public_ref"])
                click("تحرير جواب بإحالة موثقة")
                draft = "مسودة بشرية لا تضيع عند المعاينة\nوسطر ثانٍ."
                page.locator("#answer").fill(draft)
                page.locator("#edition").select_option(str(edition))
                page.locator("#query").fill("فرع")
                click("اقتراح مصادر موجودة للمراجعة", keyboard=True)
                self.assertIn("اقتراحات غير معتمدة", page.content())
                self.assertIn("(0/12)", page.content())
                click("معاينة الاقتراح 2")
                self.assertIn("معاينة المصدر الموثق", page.content())
                self.assertEqual(page.locator("#answer").input_value(), draft)
                click("العودة إلى البحث والمسودة", keyboard=True)
                self.assertEqual(page.locator("#query").input_value(), "فرع")
                click("اختيار الاقتراح 2 بعد مراجعتي")
                page.locator("#query").fill("")
                page.locator("#page").fill("3")
                click("البحث مع الاحتفاظ بالمسودة")
                click("إضافة الموضع 3 إلى القائمة")
                click("تقديم الإحالة 2", keyboard=True)
                page.locator('[name="confirm"]').check()
                click("حفظ الجواب والقائمة الكاملة")
                click("تصحيح مصدر الإحالة 1")
                page.locator("#note").fill("سبب بشري لتصحيح المصدر")
                page.locator("#page").fill("4")
                click("البحث مع الاحتفاظ بالمسودة")
                click("استبدال بالإحالة المصححة 4")
                self.assertEqual(page.locator("#answer").input_value(), draft)
                page.locator('[name="confirm"]').check()
                click("حفظ الجواب والقائمة الكاملة")
                click("عرض تاريخ الإحالات مع حفظ المسودة")
                self.assertIn("سبب بشري لتصحيح المصدر", page.content())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_function("document.documentElement.clientWidth === " + str(width))
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(OUT / f"history-{width}.png"), full_page=True)
                click("العودة إلى البحث والمسودة", keyboard=True)
                self.assertEqual(page.locator("#answer").input_value(), draft)
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "viewport_widths": [320, 1280],
                            "rtl": True,
                            "keyboard_submit": True,
                            "external_requests": external,
                            "page_errors": errors,
                            "history_reason_visible": True,
                        },
                        indent=2,
                    )
                )
            finally:
                browser.close()

        self.assertEqual(CitationCorrection.objects.count(), 1)
