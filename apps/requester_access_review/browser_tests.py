"""One synthetic browser journey across the requester and trusted staff UI."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case
from tests.casework.test_http import Directory

from .tests import SETTINGS


@override_settings(**SETTINGS)
class AccessReviewBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_request_review_verify_rotate_and_close(self):
        from playwright.sync_api import sync_playwright

        directory = Directory()

        def trusted_fixture_resolver(subject, public_ref):
            if subject != directory.current.subject_id or public_ref not in directory.current.case_keys:
                raise ValueError("untrusted_fixture_identity")
            return Case.objects.get(public_ref=public_ref).requester_id

        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                               FATWA_CASEWORK_RECOVERY_RESOLVER=trusted_fixture_resolver):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    headless=True, chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    requester_context = browser.new_context(viewport={"width": 360, "height": 800})
                    staff_context = browser.new_context(viewport={"width": 1280, "height": 900})
                    unexpected, errors = [], []
                    for context in (requester_context, staff_context):
                        def route(request_route):
                            parsed = urlsplit(request_route.request.url)
                            if parsed.netloc != urlsplit(self.live_server_url).netloc or parsed.query:
                                unexpected.append("unexpected_request")
                                request_route.abort()
                            else:
                                request_route.continue_()
                        context.route("**/*", route)
                    requester, staff = requester_context.new_page(), staff_context.new_page()
                    for page in (requester, staff):
                        page.on("pageerror", lambda error: errors.append("page_error"))

                    def click(page, name):
                        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                            page.get_by_role("button", name=name, exact=True).click()
                        self.assertEqual(navigation.value.status, 200)
                        self.assertIn("no-store", navigation.value.headers["cache-control"])

                    requester.goto(self.live_server_url + "/casework/")
                    requester.locator("#question").fill("سؤال اصطناعي لرحلة مراجعة الوصول.")
                    click(requester, "حفظ السؤال")
                    public_ref = requester.locator("#public-reference").inner_text()
                    token = requester.locator("#issued-token").inner_text()
                    requester.get_by_role("link", name="متابعة هذا السؤال", exact=True).click()
                    requester.locator("#review-reason").select_option("EXPOSED")
                    click(requester, "حفظ طلب مراجعة الوصول")
                    self.assertIn("طلب المراجعة محفوظ", requester.locator("#access-review-history").inner_text())
                    directory.grant(public_ref)
                    staff.goto(self.live_server_url + "/casework/staff/login/")
                    staff.locator("#credential").fill(directory.credential)
                    click(staff, "دخول المكتب")
                    click(staff, "بدء متابعة التحقق")
                    self.assertEqual(staff.get_by_role("button", name="إغلاق الطلب بعد إبطال الرمز السابق").count(), 0)
                    requester.reload()
                    self.assertIn("الفريق يتابع التحقق الموثوق", requester.locator("#access-review-history").inner_text())
                    click(staff, "فتح القضية والتحقق الموثوق")
                    click(staff, "استرداد رمز جديد")
                    replacement = staff.locator("#replacement-token").inner_text()
                    requester.reload()
                    self.assertEqual(requester.locator("#requester-workspace").count(), 0)
                    staff.goto(self.live_server_url + "/casework/staff/")
                    click(staff, "إغلاق الطلب بعد إبطال الرمز السابق")
                    self.assertIn("لا توجد طلبات مفتوحة", staff.content())
                    requester.locator("#workspace-token").fill(replacement)
                    click(requester, "فتح المتابعة الخاصة")
                    self.assertIn("أُغلق الطلب بعد إبطال الرمز السابق", requester.locator("#access-review-history").inner_text())
                    for width in (360, 1280):
                        requester.set_viewport_size({"width": width, "height": 900})
                        self.assertLessEqual(requester.evaluate("document.documentElement.scrollWidth"), width)
                        self.assertNotIn(token, requester.content())
                        self.assertNotIn(replacement, requester.content())
                        destination = Path("/tmp/fatwa-access-review-qa")
                        destination.mkdir(parents=True, exist_ok=True)
                        requester.screenshot(path=str(destination / f"access-review-{width}.png"), full_page=True)
                    self.assertEqual(unexpected, [])
                    self.assertEqual(errors, [])
                    print(f"Access review Chromium {browser.version}: requester request, scoped staff queue, "
                          "trusted fixture rotation, old access denied, closure, new access history; RTL 360/1280.")
                finally:
                    browser.close()
