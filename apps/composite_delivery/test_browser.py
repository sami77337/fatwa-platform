"""One focused real-browser delivery desk journey; no external requests or sends."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent
from apps.source_case_intake import services as origins
from apps.source_case_intake import simulators

from .test_desk import SETTINGS, DeskFixture

OUT = Path(".local/qa/v10-delivery-desk")


@override_settings(**SETTINGS)
class DeliveryDeskBrowserTests(DeskFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def call():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=30)

    def click(self, page, name, *, code=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            target = page.get_by_role("button", name=name, exact=True)
            target.focus()
            target.press("Enter")
        self.assertEqual(navigation.value.status, code, page.locator("main").inner_text()[:500])
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def import_part(self, page, ordinal, bundle):
        page.get_by_text(f"مطابقة إيصال الجزء {ordinal}", exact=True).click()
        form = page.locator(f"#part-{ordinal} form")
        form.locator("textarea").fill(bundle)
        form.locator('input[name="confirm"]').check()
        self.click(page, f"تسجيل إيصال الجزء {ordinal}")

    def test_native_signed_partial_failed_unknown_reconciliation_and_stale_close(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        self.a = origins.ingest(
            raw=simulators.telegram(document=True, thread=19),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        self.directory.refs = frozenset({self.a["public_ref"]})
        origins.attach_fixture(
            receipt_id=self.a["receipt_id"],
            source_file_id="synthetic-file-1",
            token=self.a["token"],
            raw=b"synthetic browser attachment",
            filename="synthetic.txt",
            media_type="text/plain",
            synthetic_fixtures_only=True,
        )
        self.approve()
        with sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            external, errors = [], []

            def route(r):
                if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                    external.append(r.request.url)
                    r.abort()
                else:
                    r.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-credential-with-32-characters")
                self.click(page, "دخول المكتب")
                self.click(page, self.a["public_ref"])
                self.click(page, "تجهيز توصيل الجواب المركب")
                self.assertIn("Telegram", page.locator("main").inner_text())
                self.assertEqual(page.locator('article[id^="part-"]').count(), 3)
                self.capture(page, "prepared-origin")
                with page.expect_download() as download:
                    page.get_by_role(
                        "button", name="تنزيل طلب إذن جميع الأجزاء", exact=True
                    ).click()
                prepared = json.loads(Path(download.value.path()).read_text())
                self.assertEqual(prepared["origin_channel"], "telegram")
                self.assertEqual(len(prepared["parts"]), 3)
                signed = self.receipt(prepared)
                page.locator("#return-permission").fill(
                    json.dumps(
                        {
                            "request_sha256": prepared["plan_sha256"],
                            "receipt": asdict(signed),
                        }
                    )
                )
                page.locator(
                    'form:has(input[value="composite_stage"]) input[name="confirm"]'
                ).check()
                self.click(page, "تسجيل خطة الأجزاء الموقّعة")
                self.assertIn("إذن مستقل موقّع متحقق", page.locator("main").inner_text())
                first = self.sync(self.reserve)
                first_part = self.sync(lambda: self.resolve(first))
                accepted = self.sync(lambda: self.bundle(first, first_part, "ACCEPTED"))
                delivered = self.sync(lambda: self.bundle(first, first_part, "DELIVERED"))
                self.click(page, "تحديث متابعة الأجزاء")
                self.import_part(page, 1, accepted)
                self.assertIn(
                    "قبول المزود فقط؛ التسليم غير مؤكد", page.locator("#part-1").inner_text()
                )
                self.assertNotIn(first.token, page.content())
                self.import_part(page, 1, delivered)
                self.assertIn("إيصال تسليم موقّع متحقق", page.locator("#part-1").inner_text())
                second = self.sync(self.reserve)
                second_part = self.sync(lambda: self.resolve(second))
                failed = self.sync(lambda: self.bundle(second, second_part, "FAILED"))
                self.click(page, "تحديث متابعة الأجزاء")
                self.import_part(page, 2, failed)
                self.assertIn("فشل يحتاج مراجعة بشرية", page.locator("#part-2").inner_text())
                third = self.sync(self.reserve)
                third_part = self.sync(lambda: self.resolve(third))
                recovered = self.sync(lambda: self.bundle(third, third_part, "DELIVERED"))
                page.locator(
                    'form:has(input[value="composite_reconcile"]) input[name="confirm"]'
                ).check()
                with patch(
                    "apps.delivery_queue.services.timezone.now",
                    return_value=timezone.now() + timedelta(minutes=2),
                ):
                    self.click(page, "مطابقة المحاولات المنتهية")
                self.assertIn("نتيجة غير محسومة", page.locator("#part-3").inner_text())
                self.capture(page, "partial-failed-unresolved")
                self.import_part(page, 3, recovered)
                self.assertIn(
                    "لم يثبت اكتمال تسليم جميع الأجزاء", page.locator("main").inner_text()
                )
                self.assertEqual(self.sync(lambda: DeliveryAttempt.objects.count()), 3)
                self.assertEqual(self.sync(lambda: DeliveryIntent.objects.count()), 3)
                self.assertIsNone(self.sync(self.reserve))
                self.capture(page, "partial-final")
                self.sync(self.save)
                self.click(page, "تحديث متابعة الأجزاء")
                self.assertIn("يلزم اعتماد بشري حالي", page.locator("main").inner_text())
                self.assertEqual(page.locator('article[id^="part-"]').count(), 0)
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                evidence = {
                    "chromium": browser.version,
                    "sandbox": sandbox,
                    "external_requests": len(external),
                    "page_errors": len(errors),
                    "parts": 3,
                    "attempts": 3,
                    "verified_parts_before_new_revision": 2,
                    "failed_parts": 1,
                    "viewports": [320, 1280],
                    "keyboard_submit": True,
                    "external_send": False,
                }
                (OUT / "result.json").write_text(json.dumps(evidence, indent=2))
                print("V10 delivery desk browser PASS " + json.dumps(evidence))
            finally:
                context.close()
                browser.close()
