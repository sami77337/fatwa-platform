"""Protected Chromium: real native chooser, preview, durable job and ZIP download."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import CaseEvent

from . import tests as fixtures
from .models import ExportArtifact, ExportEvent

OUT = Path(".local/qa/functional-completion/export-browser")


@override_settings(
    **{
        **fixtures.FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    }
)
class SelectedExportBrowserTests(fixtures.ExportFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def run():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def form(self, page, action, *, selected=False):
        scope = page.locator("#selected-export-job") if selected else page
        form = scope.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(form.count(), 1)
        return form

    def submit(self, page, action, *, selected=False, code=200):
        form = self.form(page, action, selected=selected)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button = form.locator("button").first
            button.focus()
            button.press("Enter")
        self.assertEqual(navigation.value.status, code)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_select_preview_queue_build_download_then_current_grant_revokes_retrieval(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        before = CaseEvent.objects.count()
        errors, external = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 320, "height": 900}, accept_downloads=True
            )
            context.tracing.start(screenshots=True, snapshots=True)

            def route(request):
                url = urlsplit(request.request.url)
                if url.scheme != "http" or url.netloc != urlsplit(self.live_server_url).netloc:
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.submit(page, "exports_open")
                self.assertEqual(
                    page.locator("#export-case-ref").inner_text(), self.receipt["public_ref"]
                )
                page.locator("#export-kind").select_option("REFERENCE")
                page.locator("#export-edition").select_option(str(self.catalog_id))
                page.locator("#export-query").fill("فرع")
                self.submit(page, "exports_search")
                choices = page.locator('#export-selection-form [name="selection"]')
                self.assertEqual(choices.count(), 2)
                for index in range(choices.count()):
                    choices.nth(index).check()
                page.locator("#export-format").select_option("JSONL")
                self.capture(page, "selected-sources")
                self.submit(page, "exports_prepare")
                self.assertIn("معاينة", page.locator("#export-state").inner_text())
                self.capture(page, "scope-preview")
                self.submit(page, "exports_queue", selected=True)
                self.assertIn("جاهز", page.locator("#export-state").inner_text())
                self.submit(page, "exports_build", selected=True)
                self.assertIn("اكتمل", page.locator("#export-state").inner_text())
                self.capture(page, "ready-result")
                with page.expect_download() as download:
                    button = self.form(page, "exports_download", selected=True).locator("button")
                    button.focus()
                    button.press("Enter")
                target = OUT / "selected-result.zip"
                download.value.save_as(str(target))
                self.assertIsNone(download.value.failure())
                files, manifest = self.unpack(target.read_bytes())
                records = [json.loads(line) for line in files["records.jsonl"].splitlines()]
                self.assertEqual(len(records), 2)
                self.assertEqual(manifest["included"], manifest["requested"])
                self.assertEqual(self.sync(lambda: ExportArtifact.objects.count()), 1)
                self.export_authority.denied.add(("DOWNLOAD", ""))
                self.submit(page, "exports_download", selected=True, code=409)
                self.assertIn("export_action_not_accepted", page.locator("body").inner_text())
                self.assertEqual(
                    self.sync(lambda: ExportEvent.objects.filter(action="DOWNLOAD").count()), 1
                )
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "protected_browser": True,
                            "sandbox": True,
                            "native_selected_resources": 2,
                            "formats_exercised": ["JSONL", "ZIP"],
                            "download_revocation": True,
                            "source_unchanged": True,
                            "widths": [320, 1280],
                            "page_errors": 0,
                            "external_requests": 0,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
