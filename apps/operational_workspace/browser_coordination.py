"""Native protected human priority and assignment with actual role and revocation."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.case_assignments import services as assignments
from apps.case_assignments.models import AssignmentEvent, PriorityEvent

from . import browser_tests
from .coordination_test_support import COORDINATION_FEATURES, CoordinationFixture
from .test_support import CREDENTIALS

OUT = Path(".local/qa/functional-continuation/operational-coordination-browser")


@override_settings(**COORDINATION_FEATURES)
class OperationalCoordinationBrowserTests(CoordinationFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def test_native_organizer_priority_assignment_shared_queue_and_current_revocation(self):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.skipTest("protected browser sandbox required")
        from playwright.sync_api import expect, sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "traces": ["trace.zip"],
            "page_errors": [],
            "external_requests": [],
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                headless=True,
                chromium_sandbox=True,
            )
            context = browser.new_context(locale="ar", viewport={"width": 320, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.on("pageerror", lambda error: proof["page_errors"].append(str(error)))

            def local_only(route):
                if urlsplit(route.request.url).netloc != urlsplit(self.live_server_url).netloc:
                    proof["external_requests"].append("blocked")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local_only)
            try:
                base = self.live_server_url + "/casework/operations/"
                self.assertEqual(page.goto(base + "login/").status, 200)
                page.locator('[name="credential"]').fill(CREDENTIALS["operator"])
                self.submit(page, page.locator("#ops-login button"))
                page.locator("#ops-coordination-index > summary").click()
                entry = page.locator(
                    f'#ops-coordination-index form[data-case-ref="{self.target["public_ref"]}"]'
                )
                self.submit(page, entry.locator("button"))
                expect(page.locator("#ops-actor")).to_contain_text("ORGANIZER")
                form = page.locator("#ops-priority-form")
                form.locator('[name="priority"]').select_option("fixture_urgent")
                form.locator('[name="reason"]').fill("أولوية اختارها المنظم في المتصفح")
                form.locator('[name="confirmed"]').check()
                self.assertTrue(form.evaluate("form => form.checkValidity()"))
                self.submit(page, form.locator("button"))
                expect(page.locator("#ops-priority")).to_contain_text("عاجل اصطناعي")
                form = page.locator('#ops-assignment-targets form[data-target="mufti"]')
                form.locator('[name="reason"]').fill("توزيع بشري على مفتي مخول")
                form.locator('[name="confirmed"]').check()
                self.submit(page, form.locator("button"))
                expect(page.locator("#ops-primary")).to_contain_text("mufti")
                current = self.sync(
                    lambda: assignments.read_assignment(
                        case_id=self.target["case_id"],
                        subject_id="mufti",
                        provider=self.directory,
                        synthetic_fixtures_only=True,
                    )
                )
                self.assertEqual(current["primary_subject"], "mufti")
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    name = f"saved-priority-assignment-{width}.png"
                    page.screenshot(path=str(OUT / name), full_page=True)
                    proof["screenshots"].append(name)
                form = page.locator("#ops-clear-assignment")
                form.locator('[name="reason"]').fill("إعادة بشرية للطابور المشترك")
                form.locator('[name="confirmed"]').check()
                self.submit(page, form.locator("button"))
                expect(page.locator("#ops-primary")).to_contain_text("طابور مشترك")
                self.submit(page, page.locator("#ops-coordination-back button"))
                page.locator("#ops-coordination-index > summary").click()
                expect(page.locator("#ops-coordination-index")).to_contain_text("عاجل اصطناعي")
                self.submit(page, entry.locator("button"))
                form = page.locator("#ops-priority-form")
                form.locator('[name="priority"]').select_option("fixture_normal")
                form.locator('[name="reason"]').fill("لن يمر بعد سحب الإذن")
                form.locator('[name="confirmed"]').check()
                self.sync(lambda: self.authority.revoke(action="SET_PRIORITY"))
                self.submit(page, form.locator("button"), expected=409)
                self.assertEqual(self.sync(lambda: AssignmentEvent.objects.count()), 2)
                self.assertEqual(self.sync(lambda: PriorityEvent.objects.count()), 1)
                self.assertEqual(self.sync(self.immutable_sources), self.originals)
                self.assertEqual(proof["page_errors"], [])
                self.assertEqual(proof["external_requests"], [])
                proof.update(
                    status="PASS",
                    actual_role="ORGANIZER",
                    primary_then_shared=True,
                    priority_persisted=True,
                    mufti_sees_same_assignment=True,
                    revoked_action_denied=True,
                    source_unchanged=True,
                    actual_actor_and_reason_preserved=True,
                )
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
                (OUT / "result.json").write_text(
                    json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
                )
