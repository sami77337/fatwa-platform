"""Protected native upload/retry/download journey with declared synthetic scan results."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.casework.models import Case
from apps.requester_portal.test_support import PORTAL_SETTINGS
from config.settings import campaign_review

from . import recovery_support
from .models import QuarantinedFile, ScanAttempt
from .test_support import RAW, ScanFixture

OUT = Path(".local/qa/functional-continuation/upload-security-browser")
FEATURES = {
    **PORTAL_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "MIDDLEWARE": list(campaign_review.MIDDLEWARE),
}


@override_settings(**FEATURES)
class UploadSecurityBrowserTests(ScanFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                # These are read-only observations, with bounded database waiting.
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '5s'")
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(work).result(timeout=10)

    def submit(self, page, name, expected=200):
        button = page.get_by_role("button", name=name, exact=True)
        with page.expect_navigation(wait_until="domcontentloaded") as waiting:
            button.focus()
            button.press("Enter")
        self.assertEqual(waiting.value.status, expected)
        self.assertIn("no-store", waiting.value.headers.get("cache-control", ""))

    def attach(self, page, raw, name):
        page.locator("#reply-attachment").set_input_files(
            {"name": name, "mimeType": "text/plain", "buffer": raw}
        )
        page.locator('#portal-reply-form [name="synthetic_only"]').check()

    def capture(self, page, label, proof, *, denied=False):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            if denied:
                self.assertEqual(
                    json.loads(page.locator("body").inner_text()),
                    {"error": "attachment_unavailable"},
                )
            else:
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            filename = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_native_atomic_reply_quarantine_retry_original_download_and_scan_revocation(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "scanner_mode": "SYNTHETIC",
            "real_engine_verified": False,
            "widths": [320, 1280],
            "screenshots": [],
            "traces": [],
            "external_requests": [],
            "page_errors": [],
        }
        before = recovery_support.source_pins(self.receipt["case_id"])
        text = "  رد بشري اصطناعي محفوظ في المسودة\nمع مرفق منفصل  "
        # Native multipart form submission serializes textarea line endings as
        # CRLF. Compare the exact submitted value, including surrounding spaces,
        # without normalizing the canonical evidence saved by the service.
        submitted_text = text.replace("\n", "\r\n")
        blocked = b"SYNTHETIC blocked upload; no actual malware or detection claim\n"
        unavailable = b"SYNTHETIC unavailable-engine input\n"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    viewport={"width": 320, "height": 900}, accept_downloads=True
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)

                def local_only(route):
                    target = urlsplit(route.request.url)
                    if (
                        target.scheme != "http"
                        or target.netloc != urlsplit(self.live_server_url).netloc
                    ):
                        proof["external_requests"].append("blocked")
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", local_only)
                page = context.new_page()
                page.on(
                    "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                )
                try:
                    self.assertEqual(
                        page.goto(self.live_server_url + "/casework/status/").status, 200
                    )
                    page.locator("#portal-token").fill(self.receipt["token"])
                    self.submit(page, "فتح قضيتي")
                    page.locator("#portal-followup").fill(text)
                    self.attach(page, unavailable, "unavailable.txt")
                    with self.settings(FATWA_UPLOAD_SCANNER=None):
                        self.submit(page, "إرسال التعقيب", 409)
                    self.assertEqual(page.locator("#portal-followup").input_value(), text)
                    self.assertEqual(
                        self.sync(lambda: recovery_support.source_pins(self.receipt["case_id"])),
                        before,
                    )
                    self.assertEqual(
                        self.sync(lambda: ScanAttempt.objects.get().status), "UNAVAILABLE"
                    )
                    self.assertEqual(self.scanner.calls, [])
                    self.capture(page, "unavailable-kept-draft", proof)

                    self.scanner.changes = {"status": "BLOCKED"}
                    self.attach(page, blocked, "blocked.txt")
                    self.submit(page, "إرسال التعقيب", 409)
                    self.assertEqual(page.locator("#portal-followup").input_value(), text)
                    self.assertEqual(
                        self.sync(lambda: recovery_support.source_pins(self.receipt["case_id"])),
                        before,
                    )
                    self.scanner.changes.clear()
                    self.attach(page, blocked, "renamed.txt")
                    self.submit(page, "إرسال التعقيب", 409)
                    self.assertEqual(page.locator("#portal-followup").input_value(), text)
                    self.assertEqual(len(self.scanner.calls), 1)
                    self.assertEqual(self.sync(lambda: CaseAttachment.objects.count()), 0)
                    self.capture(page, "blocked-retry-kept-draft", proof)

                    self.attach(page, RAW, "authorized-original.txt")
                    self.submit(page, "إرسال التعقيب")
                    self.assertIn("حُفظ ردك ومرفقه معًا", page.content())
                    self.assertEqual(page.locator('[data-history-kind="attachment"]').count(), 1)
                    case = self.sync(lambda: Case.objects.get(pk=self.receipt["case_id"]))
                    self.assertEqual(
                        self.sync(lambda: list(case.evidence.values_list("text", flat=True))).count(
                            submitted_text
                        ),
                        1,
                    )
                    self.assertEqual(
                        self.sync(
                            lambda: bytes(
                                QuarantinedFile.objects.get(pk=sha256(blocked).hexdigest()).original
                            )
                        ),
                        blocked,
                    )
                    self.assertEqual(self.sync(lambda: CaseAttachment.objects.count()), 1)
                    with page.expect_download() as waiting:
                        page.get_by_role("link", name="تنزيل المرفق 1", exact=True).click()
                    downloaded = waiting.value
                    self.assertIsNone(downloaded.failure())
                    destination = OUT / "authorized-original.txt"
                    downloaded.save_as(str(destination))
                    self.assertEqual(destination.read_bytes(), RAW)
                    self.capture(page, "clean-reply-and-original", proof)
                    retained = self.sync(
                        lambda: recovery_support.source_pins(self.receipt["case_id"])
                    )

                    old = self.scanner.current
                    self.scanner.current = replace(
                        old, signature_version="SYNTHETIC-revoked-signatures"
                    )
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        page.get_by_role("link", name="فتح المرفق 1", exact=True).click()
                    self.assertEqual(navigation.value.status, 404)
                    self.assertNotIn(RAW.decode(), page.content())
                    self.capture(page, "revoked-original", proof, denied=True)
                    self.scanner.current = old
                    self.assertEqual(
                        page.goto(self.live_server_url + "/casework/status/").status, 200
                    )
                    self.assertEqual(
                        self.sync(lambda: recovery_support.source_pins(self.receipt["case_id"])),
                        retained,
                    )
                    self.assertEqual(len(self.scanner.calls), 2)
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof.update(
                        status="PASS",
                        browser=browser.version,
                        native_file_picker=True,
                        unavailable_preserves_draft=True,
                        blocked_retry_is_sticky=True,
                        canonical_reply_and_file_atomic=True,
                        literal_original_bytes_preserved=True,
                        native_original_download=True,
                        original_sha256=sha256(RAW).hexdigest(),
                        late_scan_revocation_http=404,
                        fresh_scan_configuration_required=True,
                        protected_routes=[
                            "/casework/status/",
                            "/casework/status/attachments/<id>/",
                        ],
                    )
                finally:
                    context.tracing.stop(path=str(OUT / "trace-requester.zip"))
                    proof["traces"].append("trace-requester.zip")
                    context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
