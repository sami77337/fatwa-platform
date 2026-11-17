"""Actual browser: read markers, fresh evidence and delegated case opening."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework import services
from tests.casework import test_browser as browser_contract
from tests.casework.test_http import WEB_SETTINGS, Directory


@override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.team_updates.urls"})
class InboxBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_contract.CaseworkBrowserTests.sync
    submit = browser_contract.CaseworkBrowserTests.submit

    def test_seen_followup_filter_open_mobile_and_desktop(self):
        from playwright.sync_api import sync_playwright

        directory = Directory()
        case = self.sync(lambda: services.intake_case(
            original_question="سؤال اصطناعي لصندوق التحديثات", requester_id="inbox-fixture",
            source_event_id="website:inbox-fixture", idempotency_key="inbox-fixture",
            synthetic_fixtures_only=True,
        ))
        directory.grant(case["public_ref"])
        origin = self.live_server_url
        output = Path(".local/qa/team-updates/browser")
        output.mkdir(parents=True, exist_ok=True)
        external, errors = [], []
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory), sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ["FATWA_FASTBUILD_BROWSER"], headless=True,
                chromium_sandbox=True, args=["--disable-dev-shm-usage"],
            )
            try:
                ctx = browser.new_context(viewport={"width": 320, "height": 780})

                def route(request_route):
                    parsed = urlsplit(request_route.request.url)
                    if parsed.netloc != urlsplit(origin).netloc or parsed.scheme != "http" or parsed.query:
                        external.append(True)
                        request_route.abort()
                    else:
                        request_route.continue_()

                ctx.route("**/*", route)
                page = ctx.new_page()
                page.on("pageerror", lambda error: errors.append(True))
                page.goto(origin + "/casework/staff/login/")
                page.locator("#credential").fill(directory.credential)
                self.submit(page, page.get_by_role("button", name="دخول المكتب"))
                self.assertEqual(page.locator("article.update").count(), 1)
                self.submit(page, page.get_by_role("button", name="تعليم التنبيه كمقروء"))
                self.assertEqual(page.locator("#empty-updates").count(), 1)
                self.sync(lambda: services.add_followup(
                    token=case["token"], text="تعقيب اصطناعي جديد",
                    expected_revision=1, synthetic_fixtures_only=True,
                ))
                page.goto(origin + "/casework/staff/")
                self.assertIn("تعقيب جديد", page.locator("article.update").inner_text())
                self.assertNotIn("تعقيب اصطناعي جديد", page.locator("body").inner_text())
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.screenshot(path=str(output / f"inbox-{width}.png"), full_page=True)
                self.submit(page, page.get_by_role("button", name="فتح القضية"))
                self.assertEqual(page.locator("#selected-reference").inner_text(), case["public_ref"])
                self.assertIn("تعقيب اصطناعي جديد", page.locator("body").inner_text())
                page.goto(origin + "/casework/staff/")
                self.assertEqual(page.get_by_role("button", name="تعليم التنبيه كمقروء").count(), 1)
                page.locator("#state").select_option("all")
                self.submit(page, page.get_by_role("button", name="تصفية التنبيهات"))
                self.assertEqual(page.locator("article.update").count(), 2)
                self.assertIn("مقروء في صندوقك", page.locator("article.update").last.inner_text())
                self.assertFalse(external)
                self.assertFalse(errors)
                (output / "evidence.json").write_text(json.dumps({
                    "status": "PASS", "browser_version": browser.version,
                    "widths": [320, 1280], "rtl": True, "no_overflow": True,
                    "seen_marker_then_new_followup": True, "case_open_not_acknowledgement": True,
                    "external_or_query_requests": 0, "page_errors": 0,
                }, indent=2) + "\n")
                ctx.close()
            finally:
                browser.close()
