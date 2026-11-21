"""Real protected Chromium: signed source ingress -> native review -> revoked access.

All input is synthetic. This journey does not grant a provider API subscription,
approve scholarly material, execute outbound sends, or amend an original.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case
from apps.source_case_intake import services as intake
from apps.source_case_intake.http_tests import DESK_SETTINGS
from apps.source_case_intake.models import EvidenceBinding, SourceReceipt
from tests.casework.test_http import Directory

from .tests import ACCOUNT, PAGE, QUESTION, SECRET, URL, meta, profile

OUT = Path(".local/qa/webhook-ingress/browser")
FEATURES = {
    **DESK_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_WEBHOOK_INGRESS_ENABLED": True,
    "FATWA_WEBHOOK_INGRESS_PROFILES": {ACCOUNT: profile("messenger")},
    "FATWA_CASEWORK_WEB_ENABLED": True,
}


@override_settings(**FEATURES)
class SignedMetaBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_signed_capture_native_review_exact_raw_and_revocation(self):
        from playwright.sync_api import sync_playwright

        raw = json.dumps(meta("messenger"), ensure_ascii=False, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        directory = Directory()
        directory.grant(intake.REVIEW_SCOPE)
        errors, external = [], []
        OUT.mkdir(parents=True, exist_ok=True)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory), sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900}, accept_downloads=True
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(request):
                    if urlsplit(request.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(request.request.url)
                        request.abort()
                    else:
                        request.continue_()

                page.route("**/*", route)
                base = self.live_server_url
                envelope = {"Content-Type": "application/json", "X-Hub-Signature-256": signature}
                for _ in range(2):
                    accepted = context.request.post(base + URL, data=raw, headers=envelope)
                    self.assertEqual(accepted.status, 200, accepted.body())
                    self.assertEqual(accepted.body(), b"OK")
                self.assertEqual(SourceReceipt.objects.filter(source="messenger").count(), 1)
                self.assertFalse(Case.objects.exists())
                self.assertFalse(EvidenceBinding.objects.exists())

                bad = context.request.post(
                    base + URL, data=raw,
                    headers={**envelope, "X-Hub-Signature-256": "sha256=" + "0" * 64},
                )
                self.assertEqual(bad.status, 403)
                self.assertEqual(SourceReceipt.objects.count(), 1)

                page.goto(base + "/casework/staff/login/", wait_until="domcontentloaded")
                page.locator("#credential").fill(directory.credential)

                def click(name, *, keyboard=False):
                    button = page.get_by_role("button", name=name, exact=True)
                    with page.expect_navigation(wait_until="domcontentloaded") as nav:
                        if keyboard:
                            button.focus()
                            button.press("Enter")
                        else:
                            button.click()
                    self.assertEqual(nav.value.status, 200)
                    self.assertIn("no-store", nav.value.headers["cache-control"])

                click("دخول المكتب")
                page.locator("#source-filter").select_option("messenger")
                click("تصفية الأحداث", keyboard=True)
                self.assertEqual(page.locator("article[data-receipt]").count(), 1)
                self.assertIn("synthetic-mid-1", page.content())
                self.assertNotIn(QUESTION, page.content())  # previews never contain question body
                click("فتح الحدث synthetic-mid-1 من messenger")
                self.assertEqual(page.locator("#source-question").inner_text(), QUESTION)
                self.assertNotIn("rt_", page.content())

                with page.expect_download() as download:
                    page.get_by_role("button", name="تنزيل الأصل الخام", exact=True).click()
                self.assertEqual(Path(download.value.path()).read_bytes(), raw)

                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_function("document.documentElement.clientWidth === " + str(width))
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.keyboard.press("Tab")
                    self.assertNotEqual(
                        page.evaluate("document.activeElement.tagName"), "BODY"
                    )
                    page.screenshot(path=str(OUT / f"source-{width}.png"), full_page=True)
                directory.grant("unassigned")  # remove source-review scope, retain active staff identity
                vanished = page.goto(base + "/casework/staff/", wait_until="domcontentloaded")
                self.assertEqual(vanished.status, 200)
                self.assertNotIn("synthetic-mid-1", page.content())
                self.assertNotIn(QUESTION, page.content())
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                context.tracing.stop(path=str(OUT / "trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps({
                        "head_sha": os.environ.get("EXPECTED_SHA", ""),
                        "browser": browser.version,
                        "sandbox": sandbox,
                        "provider_contact": False,
                        "signed_raw_capture": True,
                        "same_event_replay_count": 1,
                        "invalid_signature_status": bad.status,
                        "source_view_original_exact": True,
                        "raw_download_exact": True,
                        "current_review_scope_revoked": True,
                        "native_rtl_widths": [320, 1280],
                        "external_requests": external,
                        "page_errors": errors,
                        "trace": "trace.zip",
                        "screenshots": ["source-320.png", "source-1280.png"],
                    }, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                context.close()
            finally:
                browser.close()
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.assertFalse(EvidenceBinding.objects.exists())
