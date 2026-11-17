"""Actual Chromium native-form acceptance at mobile and desktop widths."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .fixtures import CREDENTIAL, WEB_SETTINGS, DeskFixture


@override_settings(**WEB_SETTINGS)
class DeliveryDeskBrowserTests(DeskFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, function):
        def work():
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(work).result(timeout=20)

    def submit(self, page, button):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.click()
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers["cache-control"])

    def test_mobile_desktop_prepare_stage_expiry_late_proof_and_logout(self):
        from playwright.sync_api import sync_playwright

        output = Path(".local/qa/case-delivery-desk")
        output.mkdir(parents=True, exist_ok=True)
        evidence = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
            )
            try:
                for width, height in ((320, 780), (1280, 900)):

                    def setup_case():
                        self.a = self.intake("browser-" + str(width))
                        self.directory.refs = frozenset([self.a["public_ref"]])
                        self.approved = self.approve()
                        return self.signed_response()

                    signed = self.sync(setup_case)
                    context = browser.new_context(
                        viewport={"width": width, "height": height}, java_script_enabled=False
                    )
                    page = context.new_page()
                    errors, external = [], []
                    page.on("pageerror", lambda exc: errors.append(type(exc).__name__))
                    origin = urlsplit(self.live_server_url).netloc
                    page.on(
                        "request",
                        lambda req: (
                            external.append(req.url) if urlsplit(req.url).netloc != origin else None
                        ),
                    )
                    page.goto(self.live_server_url + "/casework/staff/login/")
                    page.get_by_label("رمز الهوية التجريبي").fill(CREDENTIAL)
                    self.submit(page, page.get_by_role("button", name="دخول المكتب"))
                    self.assertNotIn(self.foreign["public_ref"], page.content())
                    self.submit(page, page.get_by_role("button", name="فتح القضية 1"))
                    page.get_by_label("الحد الأقصى لحروف الجزء").fill("24")
                    page.get_by_label("تقسيم النص عند الحاجة").select_option("yes")
                    with page.expect_download() as downloaded:
                        page.get_by_role("button", name="تنزيل طلب الاعتماد").click()
                    exported = json.loads(Path(downloaded.value.path()).read_text())
                    self.assertEqual(exported["status"], "REQUEST_NOT_APPROVED")
                    self.submit(page, page.get_by_role("button", name="معاينة خطة الإرجاع"))
                    page.get_by_label("رد جهة الاعتماد الموقّع (JSON)").fill(signed)
                    self.submit(page, page.get_by_role("button", name="التحقق من الرد وحفظ الخطة"))
                    self.assertIn("لم يرسل الجواب", page.content())
                    self.assertEqual(page.locator("#signed-response").count(), 0)
                    lease = self.sync(self.reserve)
                    with patch(
                        "django.utils.timezone.now",
                        return_value=lease.expires_at + timedelta(seconds=1),
                    ):
                        self.submit(page, page.get_by_role("button", name="تحديث حالة التسليم"))
                        page.get_by_label("أؤكد تسجيل الحجوزات المنتهية كغير محسومة فقط").check()
                        self.submit(
                            page,
                            page.get_by_role("button", name="تسجيل المحاولات المنتهية كغير محسومة"),
                        )
                    self.assertIn("نتيجة المحاولة غير محسومة", page.content())
                    self.sync(lambda: self.record(lease))
                    self.sync(self.deliver)
                    self.submit(page, page.get_by_role("button", name="تحديث حالة التسليم"))
                    self.assertIn("تحققت جميع إثباتات التسليم", page.content())
                    self.assertIn("ليس إثبات قراءة السائل", page.content())
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    # Playwright evaluation is permitted even when page JS is disabled.
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    for secret in (
                        CREDENTIAL,
                        signed,
                        lease.token,
                        self.foreign["public_ref"],
                        self.a["token"],
                    ):
                        self.assertNotIn(secret, page.content())
                    page.screenshot(path=str(output / f"desk-{width}.png"), full_page=True)
                    self.submit(page, page.get_by_role("button", name="تسجيل الخروج"))
                    self.assertEqual(
                        page.goto(self.live_server_url + "/casework/staff/").status, 403
                    )
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    evidence.append(
                        {
                            "width": width,
                            "height": height,
                            "rtl": True,
                            "overflow": False,
                            "external_requests": 0,
                            "page_errors": 0,
                            "journey": "PASS",
                        }
                    )
                    context.close()
            finally:
                version = browser.version
                browser.close()
        (output / "browser-result.json").write_text(
            json.dumps({"status": "PASS", "browser": version, "viewports": evidence}, indent=2)
            + "\n"
        )
