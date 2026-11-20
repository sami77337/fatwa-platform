"""Protected-browser evidence for manual claim, workload navigation, and release."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import override_settings

from apps.casework import services as cases
from tests.casework import test_browser as contracts

from .models import AssignmentEvent

OUT = Path(".local/qa/case-assignments/browser")


@override_settings(
    ROOT_URLCONF="apps.team_workspace.urls",
    FATWA_CASE_ASSIGNMENTS_ENABLED=True,
    FATWA_CASE_ASSIGNMENT_CANDIDATES=None,
)
class AssignmentBrowserTests(contracts.CaseworkBrowserTests):
    def test_claim_mine_shared_release_on_mobile_and_desktop(self):
        from playwright.sync_api import sync_playwright

        receipt = self.sync(
            lambda: cases.intake_case(
                original_question="سؤال اصطناعي لتنسيق عمل المفتين",
                requester_id="assignment-browser",
                source_event_id="assignment-browser",
                idempotency_key="assignment-browser",
                synthetic_fixtures_only=True,
            )
        )
        self.directory.grant(receipt["public_ref"])
        common = dict(
            case_id=receipt["case_id"],
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        before = self.sync(lambda: cases.read_case(**common))
        origin = self.live_server_url
        external, errors = [], []
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                headless=True,
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = browser.new_context(viewport={"width": 320, "height": 780})

                def local_only(route):
                    parsed = urlsplit(route.request.url)
                    if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                        external.append(True)
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", local_only)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(True))
                page.goto(origin + contracts.LOGIN)
                page.locator("#credential").fill(self.directory.credential)
                self.submit(page, page.get_by_role("button", name="دخول المكتب"))
                page.locator("#queue-inbox").select_option("shared")
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.submit(
                    page, page.get_by_role("button", name=receipt["public_ref"], exact=True)
                )
                self.assertEqual(
                    page.locator("#selected-reference").inner_text(), receipt["public_ref"]
                )
                self.submit(
                    page, page.get_by_role("button", name="تولي القضية بصفتي المفتي الأساسي")
                )
                self.assertEqual(
                    page.locator("#primary-mufti").inner_text(), self.directory.current.subject_id
                )
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(
                        path=str(OUT / f"assignment-claimed-{width}.png"), full_page=True
                    )
                page.locator("#queue-inbox").select_option("mine")
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.assertEqual(
                    page.get_by_role("button", name=receipt["public_ref"], exact=True).count(), 1
                )
                page.locator("#queue-inbox").select_option("shared")
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.assertEqual(page.locator("#empty-queue").count(), 1)
                page.locator("#queue-inbox").select_option("mine")
                self.submit(page, page.get_by_role("button", name="عرض القضايا"))
                self.submit(
                    page, page.get_by_role("button", name=receipt["public_ref"], exact=True)
                )
                self.submit(
                    page, page.get_by_role("button", name="إعادة القضية إلى القائمة المشتركة")
                )
                self.assertEqual(page.locator("#shared-case").count(), 1)
                self.assertEqual(self.sync(lambda: AssignmentEvent.objects.count()), 2)
                self.assertEqual(self.sync(lambda: cases.read_case(**common)), before)
                self.assertFalse(external)
                self.assertFalse(errors)
                (OUT / "assignments.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser_version": browser.version,
                            "browser_sandbox": True,
                            "native_claim_release": True,
                            "scoped_mine_shared_navigation": True,
                            "assignment_events": 2,
                            "widths": [320, 1280],
                            "rtl": True,
                            "no_overflow": True,
                            "external_requests": 0,
                            "page_errors": 0,
                        },
                        indent=2,
                    )
                    + "\n"
                )
                context.close()
            finally:
                browser.close()
