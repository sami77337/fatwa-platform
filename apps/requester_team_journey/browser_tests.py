"""Real browser proof of the combined requester/team/review navigation."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case
from tests.casework.test_http import Directory

from .tests import SETTINGS


@override_settings(**SETTINGS)
class RequesterTeamBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_connected_case_clarification_answer_and_access_review(self):
        from playwright.sync_api import sync_playwright

        directory = Directory()

        def fixture_resolver(subject, public_ref):
            if subject != directory.current.subject_id or public_ref not in directory.current.case_keys:
                raise ValueError("untrusted_fixture")
            return Case.objects.get(public_ref=public_ref).requester_id

        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                               FATWA_CASEWORK_RECOVERY_RESOLVER=fixture_resolver):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
                    headless=True, args=["--disable-dev-shm-usage"],
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
                    requester.locator("#question").fill("سؤال اصطناعي للربط بين السائل والفريق.")
                    click(requester, "حفظ السؤال")
                    reference = requester.locator("#public-reference").inner_text()
                    token = requester.locator("#issued-token").inner_text()
                    requester.get_by_role("link", name="متابعة هذا السؤال", exact=True).click()
                    directory.grant(reference)
                    staff.goto(self.live_server_url + "/casework/staff/login/")
                    staff.locator("#credential").fill(directory.credential)
                    click(staff, "دخول المكتب")
                    self.assertEqual(staff.locator("#queue-heading").count(), 1)
                    click(staff, reference)
                    staff.locator("#clarification-text").fill("وضّح التفصيل الاصطناعي المطلوب.")
                    click(staff, "طلب استيضاح")
                    self.assertEqual(staff.locator("#answer-text").count(), 0)
                    requester.reload()
                    requester.locator("#workspace-followup").fill("تعقيب اصطناعي وصل من مساحة السائل.")
                    click(requester, "حفظ التعقيب")
                    click(staff, reference)
                    self.assertIn("تعقيب اصطناعي وصل", staff.content())
                    staff.locator("#answer-text").fill("جواب بشري اصطناعي لا يمثل فتوى.")
                    click(staff, "حفظ مسودة الجواب")
                    click(staff, "اعتماد هذه النسخة")
                    requester.reload()
                    self.assertIn("اكتملت مراجعة الجواب", requester.content())
                    self.assertNotIn("جواب بشري اصطناعي", requester.content())
                    requester.locator("#review-reason").select_option("EXPOSED")
                    click(requester, "حفظ طلب مراجعة الوصول")
                    click(staff, "طلبات مراجعة الوصول الخاص")
                    click(staff, "بدء متابعة التحقق")
                    self.assertIn("العودة إلى مساحة القضايا", staff.content())
                    click(staff, "فتح القضية والتحقق الموثوق")
                    self.assertEqual(staff.locator("#selected-reference").inner_text(), reference)
                    click(staff, "استرداد رمز جديد")
                    replacement = staff.locator("#replacement-token").inner_text()
                    requester.reload()
                    self.assertEqual(requester.locator("#requester-workspace").count(), 0)
                    click(staff, "طلبات مراجعة الوصول الخاص")
                    click(staff, "إغلاق الطلب بعد إبطال الرمز السابق")
                    self.assertIn("لا توجد طلبات مفتوحة", staff.content())
                    click(staff, "العودة إلى مساحة القضايا")
                    self.assertEqual(staff.locator("#queue-heading").count(), 1)
                    requester.locator("#workspace-token").fill(replacement)
                    click(requester, "فتح المتابعة الخاصة")
                    self.assertIn("أُغلق الطلب بعد إبطال الرمز السابق", requester.content())
                    output = Path("/tmp/fatwa-requester-team-qa")
                    output.mkdir(parents=True, exist_ok=True)
                    for page, name, width in ((requester, "requester", 360), (staff, "team", 1280)):
                        self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                        self.assertNotIn(token, page.content())
                        self.assertNotIn(replacement, page.content())
                        page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)
                    self.assertEqual(unexpected, [])
                    self.assertEqual(errors, [])
                    print(f"Combined Chromium {browser.version}: intake, team clarification, requester reply, "
                          "human draft/approval, access review, trusted rotation, closure, return to team PASS.")
                finally:
                    browser.close()
