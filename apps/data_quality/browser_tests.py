"""Protected native browser: inspect, diagnose a lost original, restore and recheck."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.case_attachments.storage_bindings import reference
from apps.casework.models import Case, CaseEvent

from .tests import FEATURES, QualityFixture

OUT = Path(".local/qa/functional-completion/quality-browser")


@override_settings(**FEATURES)
class QualityBrowserTests(QualityFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_current_diagnostic_refresh_and_operator_restore_preserve_case(self):
        from playwright.sync_api import sync_playwright

        self.storage()
        self.attach()
        foreign = self.intake("foreign-browser")
        owner = CaseAttachment.objects.get(case_id=self.receipt["case_id"])
        original_ref = reference(owner)
        path = self.storage_root / "objects" / owner.storage_key
        original_bytes = path.read_bytes()
        before = list(Case.objects.values()), list(CaseEvent.objects.values())
        OUT.mkdir(parents=True, exist_ok=True)
        errors, failed, external = [], [], []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True)

            def route(request):
                target = urlsplit(request.request.url)
                if (
                    target.scheme != "http"
                    or target.netloc != urlsplit(self.live_server_url).netloc
                ):
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "response",
                lambda response: failed.append(response.url) if response.status >= 400 else None,
            )

            def capture(name):
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertTrue(
                        page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    )
                    page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

            def refresh():
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.locator("#quality-refresh").press("Enter")

            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(self.directory.credential)
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                    page.get_by_role("link", name="جودة البيانات والروابط", exact=True).click()
                self.assertEqual(navigation.value.status, 200)
                self.assertEqual(
                    page.locator('[data-quality-check="attachments"]').get_attribute(
                        "data-quality-state"
                    ),
                    "OK",
                )
                self.assertNotIn("PRIVATE ORIGINAL", page.content())
                self.assertNotIn(foreign["public_ref"], page.content())
                capture("current-required-original")

                # Fault and repair are explicit test-operator actions against a
                # temporary owned synthetic store, never browser repair actions.
                path.unlink()
                refresh()
                self.assertEqual(
                    page.locator('[data-quality-check="attachments"]').get_attribute(
                        "data-quality-state"
                    ),
                    "TECHNICAL",
                )
                self.assertNotIn(owner.storage_key, page.content())
                self.assertNotIn(str(self.storage_root), page.content())
                capture("missing-required-original")
                self.storage_adapter.restore(original_ref, original_bytes)
                refresh()
                self.assertEqual(
                    page.locator('[data-quality-check="attachments"]').get_attribute(
                        "data-quality-state"
                    ),
                    "OK",
                )
                capture("restored-required-original")
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
        self.assertEqual(before, (list(Case.objects.values()), list(CaseEvent.objects.values())))
        self.assertEqual((errors, failed, external), ([], [], []))
        (OUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "sandbox": True,
                    "widths": [320, 1280],
                    "case_unchanged": True,
                    "required_original_lost_then_restored": True,
                    "external_requests": external,
                    "browser_errors": errors,
                    "failed_responses": failed,
                },
                indent=2,
            )
            + "\n"
        )
