"""Real role-specific classification, independent content access and revocation."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.operational_workspace.test_support import CREDENTIALS

from .campaign_test_support import FEATURES, CampaignFixture
from .catalog import LEVELS
from .models import ClassificationRevision

OUT = Path(".local/qa/functional-continuation/data-privacy-browser")


@override_settings(**FEATURES)
class DataPrivacyBrowserTests(CampaignFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, call):
        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def submit(self, page, button, *, expected=200):
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, page.locator("body").inner_text()[:500])

    def inspect(self, page):
        card = page.locator(f'[data-privacy-target="{self.target.identifier}"]')
        self.submit(page, card.get_by_role("button", name="فتح سجل التصنيف", exact=True))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_four_levels_two_roles_independent_read_and_current_revocation(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected native privacy proof requires FATWA_BROWSER_SANDBOX=1")
        self.assertIn("apps.data_privacy.integration.PrivacyResponses", settings.MIDDLEWARE)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                for subject, prefix in (
                    ("mufti", "/casework/staff/"),
                    ("admin", "/casework/operations/"),
                ):
                    context = browser.new_context(viewport={"width": 320, "height": 900})
                    contexts.append(context)

                    def route(request):
                        url = urlsplit(request.request.url)
                        if (
                            url.scheme != "http"
                            or url.netloc != urlsplit(self.live_server_url).netloc
                        ):
                            external.append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()

                    context.route("**/*", route)
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(self.live_server_url + prefix + "login/")
                    page.locator('[name="credential"]').fill(CREDENTIALS[subject])
                    self.submit(page, page.locator('form:has(input[name="credential"]) button'))
                    # Managing classification never grants the underlying case read.
                    self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        page.get_by_role("link", name="تصنيف الخصوصية", exact=True).click()
                    self.assertEqual(navigation.value.status, 200)
                    self.inspect(page)
                    levels = LEVELS if subject == "mufti" else ("CONFIDENTIAL",)
                    for level in levels:
                        page.locator("#privacy-level").select_option(level)
                        page.locator("#privacy-note").fill(
                            "قرار بشري اصطناعي مستقل <script> لا يغير الأصل"
                        )
                        page.locator('[name="confirmed"]').check()
                        self.submit(
                            page, page.get_by_role("button", name="حفظ قرار التصنيف", exact=True)
                        )
                        self.assertEqual(
                            page.locator("#privacy-record").get_attribute("data-level"), level
                        )
                        self.assertIn("<script>", page.locator("#privacy-record").inner_text())
                    self.capture(page, subject + "-dated-classification")
                    self.assertEqual(self.sync(self.source_rows), self.originals)
                    self.assertEqual(page.goto(self.live_server_url + prefix).status, 200)
                    self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    page.goto(self.live_server_url + prefix + "privacy/")
                    self.inspect(page)
                    if subject == "admin":
                        # Revoke the actual management authority after the form was rendered.
                        self.authority.grants = {
                            key: value
                            for key, value in self.authority.grants.items()
                            if dict(key)["subject_id"] != "admin"
                        }
                        page.locator("#privacy-level").select_option("RESTRICTED")
                        page.locator("#privacy-note").fill("يجب رفض هذا الطلب بعد السحب")
                        page.locator('[name="confirmed"]').check()
                        self.submit(
                            page,
                            page.get_by_role("button", name="حفظ قرار التصنيف", exact=True),
                            expected=404,
                        )
                        self.assertNotIn(self.target.identifier, page.locator("body").inner_text())
                self.assertEqual(self.sync(lambda: ClassificationRevision.objects.count()), 5)
                self.assertEqual(self.sync(self.source_rows), self.originals)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["MUFTI", "ORGANIZER_ADMIN"],
                            "levels": list(LEVELS),
                            "history_rows": 5,
                            "management_grants_no_content_read": True,
                            "post_render_revocation_denied": True,
                            "originals_unchanged": True,
                            "external_requests": external,
                            "page_errors": errors,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                    context.close()
                browser.close()
