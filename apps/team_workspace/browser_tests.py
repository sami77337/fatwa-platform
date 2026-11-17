"""Browser contracts and the new filter / return / edit interaction."""

import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import override_settings

from apps.casework import services
from tests.casework import test_browser as contracts

OUT = Path(".local/qa/team-workspace/browser")


@override_settings(ROOT_URLCONF="apps.team_workspace.urls")
class TeamWorkspaceBrowserTests(contracts.CaseworkBrowserTests):
    def setUp(self):
        super().setUp()
        output = patch.object(contracts, "OUT", OUT)
        output.start()
        self.addCleanup(output.stop)

    def test_filter_return_edit_mobile_and_desktop(self):
        from playwright.sync_api import sync_playwright

        case = self.sync(lambda: services.intake_case(
            original_question="سؤال اصطناعي لمساحة الفريق", requester_id="team-fixture",
            source_event_id="website:team-fixture", idempotency_key="team-fixture",
            synthetic_fixtures_only=True,
        ))
        self.directory.grant(case["public_ref"])
        origin = self.live_server_url
        external, errors = [], []
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ["FATWA_FASTBUILD_BROWSER"], headless=True,
                chromium_sandbox=True, args=["--disable-dev-shm-usage"],
            )
            try:
                ctx = browser.new_context(viewport={"width": 320, "height": 780})

                def route(request_route):
                    parsed = urlsplit(request_route.request.url)
                    if parsed.netloc != urlsplit(origin).netloc or parsed.scheme != "http":
                        external.append(True)
                        request_route.abort()
                    else:
                        request_route.continue_()

                ctx.route("**/*", route)
                page = ctx.new_page()
                page.on("pageerror", lambda error: errors.append(True))
                page.goto(origin + contracts.LOGIN)
                page.locator("#credential").fill(self.directory.credential)
                self.submit(page, page.get_by_role("button", name="دخول المكتب"))
                page.locator("#queue-state").select_option("waiting")
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.assertEqual(page.locator("#empty-queue").count(), 1)
                page.locator("#queue-state").select_option("all")
                page.locator("#queue-query").fill(case["public_ref"])
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.submit(page, page.get_by_role("button", name=case["public_ref"], exact=True))
                page.locator("#answer-text").fill("مسودة الفريق الاصطناعية الأولى")
                self.submit(page, page.get_by_role("button", name="حفظ مسودة الجواب"))
                page.locator("#return-note").fill("راجع الوصف في المثال الاصطناعي")
                self.submit(page, page.get_by_role("button", name="إعادة للمراجعة"))
                self.assertEqual(page.get_by_role("button", name="اعتماد هذه النسخة").count(), 0)
                self.submit(page, page.get_by_role("button", name=case["public_ref"], exact=True))
                self.assertIn("راجع الوصف", page.locator("#history").inner_text())
                self.assertEqual(page.locator("#answer-text").input_value(),
                                 "مسودة الفريق الاصطناعية الأولى")
                page.locator("#answer-text").fill("مسودة منقحة اصطناعية")
                self.submit(page, page.get_by_role("button", name="حفظ مسودة الجواب"))
                self.assertEqual(page.get_by_role("button", name="اعتماد هذه النسخة").count(), 1)
                self.submit(page, page.get_by_role("button", name="اعتماد هذه النسخة"))
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.screenshot(path=str(OUT / f"team-review-{width}.png"), full_page=True)
                self.assertFalse(external)
                self.assertFalse(errors)
                (OUT / "team-review.json").write_text(json.dumps({
                    "status": "PASS", "browser_version": browser.version,
                    "filter_return_edit_approve": True, "return_reason_persisted": True,
                    "widths": [320, 1280], "rtl": True, "no_overflow": True,
                    "external_requests": 0, "page_errors": 0,
                }, indent=2) + "\n")
                ctx.close()
            finally:
                browser.close()
