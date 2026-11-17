"""One connected real-browser journey on mobile and desktop, synthetic only."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case
from tests.casework.test_http import Directory
from tests.casework.test_requester_workspace import WORKSPACE_SETTINGS


@override_settings(**WORKSPACE_SETTINGS)
class RequesterWorkspaceBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def run():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=20)

    def test_receipt_private_workspace_staff_clarification_reply_and_reopen(self):
        from playwright.sync_api import sync_playwright

        directory = Directory()
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    headless=True,
                    chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    requester_context = browser.new_context(viewport={"width": 360, "height": 800})
                    staff_context = browser.new_context(viewport={"width": 1280, "height": 900})
                    external = []
                    errors = []
                    for context in (requester_context, staff_context):
                        def route(request_route):
                            parsed = urlsplit(request_route.request.url)
                            if parsed.netloc != urlsplit(self.live_server_url).netloc or parsed.query:
                                external.append("unexpected_request")
                                request_route.abort()
                            else:
                                request_route.continue_()
                        context.route("**/*", route)
                    requester = requester_context.new_page()
                    staff = staff_context.new_page()
                    for page in (requester, staff):
                        page.on("pageerror", lambda error: errors.append("page_error"))

                    def click(page, label):
                        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                            page.get_by_role("button", name=label, exact=True).click()
                        self.assertEqual(navigation.value.status, 200)
                        self.assertIn("no-store", navigation.value.headers["cache-control"])

                    requester.goto(self.live_server_url + "/casework/")
                    requester.locator("#question").fill("سؤال اصطناعي لتجربة المتابعة المتصلة.")
                    click(requester, "حفظ السؤال")
                    public_ref = requester.locator("#public-reference").inner_text()
                    token = requester.locator("#issued-token").inner_text()
                    requester.get_by_role("link", name="متابعة هذا السؤال", exact=True).click()
                    self.assertEqual(requester.locator("#workspace-reference").inner_text(), public_ref)
                    self.assertNotIn(token, requester.content())
                    self.assertEqual(requester.locator("#workspace-token").input_value(), "")
                    directory.grant(public_ref)

                    staff.goto(self.live_server_url + "/casework/staff/login/")
                    staff.locator("#credential").fill(directory.credential)
                    click(staff, "دخول المكتب")
                    click(staff, public_ref)
                    staff.locator("#clarification-text").fill("وضّح هذا التفصيل الاصطناعي.")
                    click(staff, "طلب استيضاح")
                    requester.get_by_role("link", name="تحديث الحالة", exact=True).click()
                    self.assertIn("وضّح هذا التفصيل", requester.locator("#requested-clarification").inner_text())
                    requester.locator("#workspace-followup").fill("تعقيب اصطناعي من مساحة المتابعة.")
                    click(requester, "حفظ التعقيب")
                    self.assertEqual(requester.locator("#followup-count").inner_text(), "1")
                    requester.reload()
                    self.assertEqual(requester.locator("#followup-count").inner_text(), "1")
                    click(staff, public_ref)
                    self.assertIn("تعقيب اصطناعي من مساحة المتابعة.", staff.content())
                    self.assertEqual(self.sync(lambda: Case.objects.get(public_ref=public_ref).evidence.count()), 2)

                    for width in (360, 1280):
                        requester.set_viewport_size({"width": width, "height": 900})
                        self.assertLessEqual(requester.evaluate("document.documentElement.scrollWidth"), width)
                        self.assertEqual(requester.locator("html").get_attribute("dir"), "rtl")
                        self.assertNotIn(token, requester.content())
                        destination = Path(os.environ.get("FATWA_REQUESTER_SCREENSHOTS", "/tmp/fatwa-requester-qa"))
                        destination.mkdir(parents=True, exist_ok=True)
                        requester.screenshot(path=str(destination / f"workspace-{width}.png"), full_page=True)
                    click(requester, "إغلاق الوصول الخاص")
                    self.assertEqual(requester.locator("#requester-workspace").count(), 0)
                    requester.locator("#workspace-token").fill(token)
                    click(requester, "فتح المتابعة الخاصة")
                    self.assertEqual(requester.locator("#workspace-reference").inner_text(), public_ref)
                    self.assertEqual(external, [])
                    self.assertEqual(errors, [])
                    print(f"Requester Chromium {browser.version}: receipt, staff clarification, reply, "
                          "refresh, close/reopen, RTL 360/1280 passed; no external requests.")
                finally:
                    browser.close()
