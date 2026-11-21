"""Protected Chromium: upload, arbitrary columns, independent reviewer, canonical reader."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.research_library.models import LibraryDecision, LibraryVersion
from apps.research_library.test_support import video

from . import formats
from . import tests as fixtures
from .models import GroupResult, RoundtripReceipt
from .test_formats import archive

OUT = Path(".local/qa/library-operations/import-browser")


@override_settings(**{**fixtures.FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class MaterialImportBrowserTests(fixtures.ImportFixture, LiveServerTestCase):
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

    def form(self, page, action):
        if action == "mi_approve":
            form = page.locator("#import-review-form")
            form.locator('[name="action"]').select_option("mi_approve")
        else:
            form = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(form.count(), 1)
        return form

    def submit(self, page, action, code=200):
        form = self.form(page, action)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button = form.locator("button").first
            button.focus()
            button.press("Enter")
        self.assertEqual(navigation.value.status, code)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def login(self, context, credential):
        page = context.new_page()
        page.goto(self.live_server_url + "/casework/staff/login/")
        page.locator("#credential").fill(credential)
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.submit(page, "open")
        self.submit(page, "mi_open")
        return page

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def library_decision(self, page, command):
        form = page.locator(f'form.library-decision[data-command="{command}"]')
        self.assertEqual(form.count(), 1)
        form.locator('[name="note"]').fill("راجعت النسخة الاصطناعية وحق تصديرها فقط")
        form.locator('[name="confirmed"]').check()
        if command == "APPROVE":
            form.locator('[name="uses"][value="EXPORT"]').check()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            form.locator("button").press("Enter")
        self.assertEqual(navigation.value.status, 200)

    def reopen_import(self, page):
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.get_by_role("link", name="مكتب الشيخ", exact=True).click()
        self.submit(page, "open")
        self.submit(page, "mi_open")

    def test_native_independent_import_to_actual_library_version(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external = [], []
        source = [
            {
                "_synthetic": True,
                "source_key": "browser-book",
                "type_name": "VIDEO",
                "title_text": "فيديو اصطناعي أدخله المتصفح",
                "work_name": "عمل تجريبي مستقل",
                "version_code": "browser-v1",
                "recorded_text": "نص اختبار حرفي\r\nلا يمثل مادة علمية",
                "file_member": "files/source.webm",
            }
        ]
        video_bytes = video()
        source_zip = archive(
            source, [("files/source.webm", "source.webm", "video/webm", video_bytes)]
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            author = browser.new_context(viewport={"width": 320, "height": 900})
            reviewer = browser.new_context(viewport={"width": 1280, "height": 900})
            publisher = browser.new_context(viewport={"width": 1280, "height": 900})
            for context in (author, reviewer, publisher):
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
                context.on(
                    "page",
                    lambda page: page.on("pageerror", lambda error: errors.append(str(error))),
                )
            try:
                page = self.login(author, "synthetic-editor-credential-32-characters")
                page.locator("#import-source-file").set_input_files(
                    {
                        "name": "mapped-source.zip",
                        "mimeType": "application/zip",
                        "buffer": source_zip,
                    }
                )
                page.locator("#import-namespace").fill("synthetic-browser-import")
                page.locator("#import-provenance").fill("مولد في اختبار المتصفح؛ مصدر اصطناعي محدد")
                page.locator("#import-rights").fill("مثال اصطناعي؛ لا يمنح اعتمادًا أو نشرًا")
                page.locator('[name="synthetic"]').check()
                self.submit(page, "mi_upload")
                for target, column in {
                    "external_id": "source_key",
                    "kind": "type_name",
                    "title": "title_text",
                    "work_title": "work_name",
                    "source_version": "version_code",
                    "recorded_text": "recorded_text",
                    "file_member": "file_member",
                }.items():
                    page.locator("#map-" + target).select_option(column)
                self.capture(page, "column-mapping")
                self.submit(page, "mi_map")
                self.submit(page, "mi_plan")
                self.assertEqual(self.sync(lambda: LibraryVersion.objects.count()), 0)
                self.assertEqual(page.locator("#import-review-form").count(), 0)
                self.capture(page, "exact-plan")
                review_page = self.login(reviewer, "synthetic-reviewer-credential-32-characters")
                self.submit(review_page, "mi_batch")
                review_page.locator("#import-review-note").fill(
                    "راجعت ربط الأعمدة والنسخة المقصودة"
                )
                review_page.locator("#import-verification-note").fill(
                    "تحققت من مثال الاختبار وبصمته؛ لا توثيق لمصدر خارجي"
                )
                self.submit(review_page, "mi_approve")
                self.submit(page, "mi_batch")
                self.submit(page, "mi_apply")
                self.assertIn("اكتمل النطاق", page.locator("#import-state").inner_text())
                self.capture(page, "canonical-receipt")
                self.assertEqual(self.sync(lambda: GroupResult.objects.count()), 1)
                self.assertEqual(
                    self.sync(lambda: LibraryVersion.objects.get().payload["recorded_text"]),
                    source[0]["recorded_text"],
                )
                self.assertEqual(self.sync(lambda: LibraryDecision.objects.count()), 0)
                self.submit(page, "rl_item")
                self.assertIn(source[0]["title_text"], page.locator("body").inner_text())
                self.capture(page, "canonical-library-reader")
                # Import approval does not authorize export. Two separate native
                # source decisions grant only EXPORT to this exact new version.
                self.submit(review_page, "mi_batch")
                self.submit(review_page, "rl_item")
                self.library_decision(review_page, "REVIEW")
                publishing_page = self.login(
                    publisher, "synthetic-publisher-credential-32-characters"
                )
                self.submit(publishing_page, "mi_batch")
                self.submit(publishing_page, "rl_item")
                self.library_decision(publishing_page, "APPROVE")
                self.reopen_import(page)
                self.submit(page, "mi_export_open")
                self.assertEqual(
                    page.locator('#roundtrip-selection-form input[name="selection"]').count(), 1
                )
                page.locator('#roundtrip-selection-form input[name="selection"]').check()
                self.submit(page, "mi_export_preview")
                self.capture(page, "selected-roundtrip-preview")
                with page.expect_download() as delivery:
                    self.form(page, "mi_export").locator("button").press("Enter")
                download = delivery.value
                self.assertIsNone(download.failure())
                raw = Path(download.path()).read_bytes()
                parsed = formats.parse(raw, download.suggested_filename)
                self.assertEqual(parsed.rows[0]["recorded_text"], source[0]["recorded_text"])
                self.assertEqual(parsed.rows[0]["external_id"], source[0]["source_key"])
                self.assertEqual(parsed.rows[0]["kind"], "VIDEO")
                self.assertEqual(parsed.files[parsed.rows[0]["file_member"]].raw, video_bytes)
                self.assertEqual(len(parsed.rows), 1)
                self.assertEqual(self.sync(lambda: RoundtripReceipt.objects.count()), 1)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "protected_browser": True,
                            "widths": [320, 1280],
                            "independent_authenticated_reviewer": True,
                            "arbitrary_source_columns": True,
                            "actual_canonical_versions": 1,
                            "native_independent_export_use_review": True,
                            "explicit_selected_roundtrip_download": True,
                            "actual_video_bytes_exported": True,
                            "scientific_approval_or_release": False,
                            "page_errors": 0,
                            "external_requests": 0,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                author.tracing.stop(path=str(OUT / "author-trace.zip"))
                reviewer.tracing.stop(path=str(OUT / "reviewer-trace.zip"))
                publisher.tracing.stop(path=str(OUT / "publisher-trace.zip"))
                author.close()
                reviewer.close()
                publisher.close()
                browser.close()
