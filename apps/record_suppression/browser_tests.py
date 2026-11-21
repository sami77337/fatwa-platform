"""One protected native administrative journey and current requester/organizer use."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.operational_workspace import browser_tests as operational_browser
from apps.operational_workspace.test_support import CREDENTIALS

from .models import SuppressionEvent
from .test_support import FEATURES, Fixture

OUT = Path(".local/qa/functional-continuation/record-suppression-browser")


@override_settings(**FEATURES)
class RecordSuppressionBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = operational_browser.OperationalWorkspaceBrowserTests.sync
    submit = operational_browser.OperationalWorkspaceBrowserTests.submit

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def inspect(self, page):
        self.submit(page, page.locator(f'[data-target="{self.receipt["case_id"]}"] button'))

    def change_native(self, page):
        page.locator('[data-action="change"] [name="reason"]').fill(
            "قرار إداري محدد قابل للاستعادة"
        )
        self.submit(page, page.locator('[data-action="change"] button'))
        self.assertEqual(page.locator('[data-action="confirm"]').count(), 1)
        page.locator('[data-action="confirm"] [name="confirmed"]').check()
        self.submit(page, page.locator('[data-action="confirm"] button'))
        self.assertEqual(page.locator("[data-result]").count(), 1)

    def unlock(self, page):
        self.assertEqual(page.goto(self.live_server_url + "/casework/status/").status, 200)
        page.locator('[name="token"]').fill(self.receipt["token"])
        self.submit(page, page.locator('form:has([name="token"]) button'))
        self.assertIn(self.receipt["public_ref"], page.locator("body").inner_text())

    def test_native_preview_soft_delete_current_denials_and_audited_restore(self):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected record-suppression evidence requires FATWA_BROWSER_SANDBOX=1")
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        (OUT / "navigation.json").unlink(missing_ok=True)
        for trace in OUT.glob("trace-*.zip"):
            trace.unlink()
        errors, external, contexts, traced, navigation = [], [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER") or None,
                headless=True,
                chromium_sandbox=True,
            )
            try:
                pages = {}
                for subject in ("admin", "operator", "requester"):
                    context = browser.new_context(
                        locale="ar", viewport={"width": 1280, "height": 900}
                    )
                    contexts.append(context)

                    def route(request):
                        if (
                            urlsplit(request.request.url).netloc
                            != urlsplit(self.live_server_url).netloc
                        ):
                            external.append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()

                    context.route("**/*", route)
                    context.tracing.start(screenshots=True, snapshots=True)
                    traced.append(context)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def record_response(response, subject=subject):
                        if response.request.is_navigation_request():
                            navigation.append(
                                {
                                    "subject": subject,
                                    "method": response.request.method,
                                    "path": urlsplit(response.url).path,
                                    "status": response.status,
                                }
                            )

                    page.on("response", record_response)
                    if subject != "requester":
                        self.assertEqual(
                            page.goto(self.live_server_url + "/casework/operations/login/").status,
                            200,
                        )
                        page.locator('[name="credential"]').fill(CREDENTIALS[subject])
                        self.submit(page, page.locator("#ops-login button"))
                    pages[subject] = page
                admin, operator, requester = pages["admin"], pages["operator"], pages["requester"]
                self.unlock(requester)
                self.assertEqual(
                    operator.locator(
                        f'article[data-case-ref="{self.receipt["public_ref"]}"]'
                    ).count(),
                    1,
                )
                path = self.live_server_url + "/casework/operations/record-lifecycle/"
                self.assertEqual(admin.goto(path).status, 200)
                self.inspect(admin)
                self.assertNotIn(
                    self.intake["original_question"], admin.locator("body").inner_text()
                )
                admin.locator('[data-action="change"] [name="reason"]').fill(
                    "إخفاء إداري دون إتلاف أصل"
                )
                self.submit(admin, admin.locator('[data-action="change"] button'))
                self.assertEqual(self.sync(lambda: SuppressionEvent.objects.count()), 0)
                self.capture(admin, "review-before-deletion")
                admin.locator('[data-action="confirm"] [name="confirmed"]').check()
                self.submit(admin, admin.locator('[data-action="confirm"] button'))
                self.assertEqual(admin.locator('[data-result="SOFT_DELETE"]').count(), 1)
                self.assertEqual(self.sync(lambda: SuppressionEvent.objects.count()), 1)
                self.assertEqual(urlsplit(requester.url).path, "/casework/status/")
                self.assertEqual(requester.reload().status, 404)
                self.assertEqual(urlsplit(requester.url).path, "/casework/status/")
                self.assertNotIn(self.receipt["public_ref"], requester.locator("body").inner_text())
                self.assertEqual(operator.reload().status, 200)
                self.assertEqual(operator.locator("article[data-case-ref]").count(), 0)
                self.assertEqual(admin.goto(path).status, 200)
                self.inspect(admin)
                self.assertEqual(admin.locator('[data-state="SOFT_DELETED"]').count(), 1)
                self.assertEqual(admin.locator("[data-audit]").count(), 1)
                self.capture(admin, "saved-deletion-audit")
                self.change_native(admin)
                self.assertEqual(admin.locator('[data-result="RESTORE"]').count(), 1)
                self.unlock(requester)
                self.assertEqual(operator.reload().status, 200)
                self.assertEqual(
                    operator.locator(
                        f'article[data-case-ref="{self.receipt["public_ref"]}"]'
                    ).count(),
                    1,
                )
                self.assertEqual(admin.goto(path).status, 200)
                self.inspect(admin)
                self.assertEqual(admin.locator('[data-state="RESTORED"]').count(), 1)
                self.assertEqual(admin.locator("[data-audit]").count(), 2)
                self.capture(admin, "restored-with-history")
                self.assertEqual(
                    self.sync(lambda: self.read()["original_question"]),
                    self.intake["original_question"],
                )
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
            finally:
                failed = sys.exc_info()[0] is not None
                cleanup_errors = []
                for index, context in enumerate(traced):
                    try:
                        context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                    except Exception as exc:
                        cleanup_errors.append(f"trace-{index}: {type(exc).__name__}")
                for index, context in enumerate(contexts):
                    try:
                        context.close()
                    except Exception as exc:
                        cleanup_errors.append(f"context-{index}: {type(exc).__name__}")
                try:
                    browser.close()
                except Exception as exc:
                    cleanup_errors.append(f"browser: {type(exc).__name__}")
                try:
                    (OUT / "navigation.json").write_text(
                        json.dumps(
                            {"navigation": navigation, "cleanup_errors": cleanup_errors},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                except Exception as exc:
                    cleanup_errors.append(f"navigation: {type(exc).__name__}")
                if not failed:
                    self.assertEqual(cleanup_errors, [])
        (OUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "native_journeys": 1,
                    "actual_admin_role": "ORGANIZER_ADMIN",
                    "audit_revisions": 2,
                    "requester_denied_after_deletion": True,
                    "organizer_count_filtered": True,
                    "positive_reads_after_restore": True,
                    "original_preserved": True,
                    "no_purge": True,
                    "page_errors": errors,
                    "external_requests": external,
                    "widths": [320, 1280],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
