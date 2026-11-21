"""Actual native explicit selection, signed staging and delivery reconciliation."""

import json
import os
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent

from . import services, test_browser
from .test_selection import FEATURES, SelectionFixture

OUT = Path(".local/qa/functional-continuation/composite-choice-browser")


@override_settings(**FEATURES)
class CompositeChoiceBrowserTests(SelectionFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = test_browser.DeliveryDeskBrowserTests.sync
    click = test_browser.DeliveryDeskBrowserTests.click
    import_part = test_browser.DeliveryDeskBrowserTests.import_part

    def read_original(self, part_id):
        return media.staff_read(
            **{key: value for key, value in self.staff().items() if key != "case_id"},
            part_id=part_id,
        )["raw"]

    def capture(self, page, name, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            path = OUT / f"{name}-{width}.png"
            page.screenshot(path=str(path), full_page=True)
            proof["screenshots"].append(path.name)

    def test_native_explicit_text_selection_preserves_audio_and_requires_independent_signed_plan(
        self,
    ):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "traces": [],
            "trace": "trace.zip",
            "page_errors": [],
            "external_requests": [],
        }
        full = self.sync(self.request)
        audio = next(part for part in full["parts"] if part["kind"] == "AUDIO")
        original_audio = self.sync(lambda: self.read_original(audio["id"]))
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                context = browser.new_context(viewport={"width": 320, "height": 780})
                context.tracing.start(screenshots=True, snapshots=True, sources=True)

                def local_only(route):
                    if urlsplit(route.request.url).netloc != urlsplit(self.live_server_url).netloc:
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
                        page.goto(self.live_server_url + "/casework/staff/login/").status, 200
                    )
                    page.locator("#credential").fill("synthetic-credential-with-32-characters")
                    self.click(page, "دخول المكتب")
                    self.click(page, self.a["public_ref"])
                    # The current Mufti workspace has a visible tab and a separate
                    # collapsed journey shortcut; neither uses the legacy label.
                    entry = page.locator(
                        '.mufti-case-nav > form:has(> input[name="action"][value="composite_open"]) > button'
                    )
                    self.assertEqual(entry.count(), 1)
                    self.assertTrue(entry.is_visible())
                    with page.expect_navigation(wait_until="domcontentloaded") as opened:
                        entry.focus()
                        entry.press("Enter")
                    self.assertEqual(opened.value.status, 200)
                    self.assertIn("no-store", opened.value.headers.get("cache-control", ""))
                    self.assertEqual(page.locator('article[id^="part-"]').count(), 3)
                    self.assertEqual(
                        page.locator("#delivery-selection").get_attribute("data-selection"), "ALL"
                    )
                    page.locator('#choose-text-only input[name="confirm"]').check()
                    self.click(page, "معاينة خطة النص فقط")
                    self.assertEqual(
                        page.locator("#delivery-selection").get_attribute("data-selection"),
                        "TEXT_ONLY",
                    )
                    self.assertEqual(page.locator('article[id^="part-"]').count(), 1)
                    self.assertEqual(page.locator("#omitted-parts li").count(), 2)
                    self.assertEqual(self.sync(lambda: DeliveryIntent.objects.count()), 0)
                    self.capture(page, "explicit-omissions", proof)
                    with page.expect_download() as download:
                        page.get_by_role(
                            "button", name="تنزيل طلب إذن النص فقط", exact=True
                        ).click()
                    prepared = json.loads(Path(download.value.path()).read_text())
                    self.assertEqual(prepared["selection_mode"], "TEXT_ONLY")
                    self.assertEqual(len(prepared["parts"]), 1)
                    self.assertEqual(prepared["manifest_sha256"], full["manifest_sha256"])
                    self.assertNotEqual(prepared["plan_sha256"], full["plan_sha256"])
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
                    lease = self.sync(self.reserve)
                    part = self.sync(lambda: self.resolve(lease))
                    self.assertEqual(part["kind"], "TEXT")
                    bundle = self.sync(lambda: self.bundle(lease, part, "DELIVERED"))
                    self.click(page, "تحديث متابعة الأجزاء")
                    self.import_part(page, 1, bundle)
                    self.assertIn("إيصال تسليم موقّع متحقق", page.locator("#part-1").inner_text())
                    self.assertEqual(page.locator("#omitted-parts li").count(), 2)
                    self.assertEqual(self.sync(lambda: DeliveryIntent.objects.count()), 1)
                    self.assertEqual(self.sync(lambda: DeliveryAttempt.objects.count()), 1)
                    self.assertEqual(self.sync(lambda: AnswerManifest.objects.get().part_count), 3)
                    self.assertEqual(self.sync(lambda: AnswerPart.objects.count()), 3)
                    self.assertIsNone(self.sync(self.reserve))
                    self.assertEqual(
                        self.sync(lambda: self.read_original(audio["id"])),
                        original_audio,
                    )
                    status = self.sync(
                        lambda: services.composite_status(
                            **self.staff(), verifier=self.channel_verifier
                        )
                    )
                    self.assertTrue(status["delivery_verified"])
                    self.assertFalse(status["read_confirmed"])
                    self.capture(page, "selected-text-delivered", proof)
                    self.directory.refs = frozenset()
                    self.click(page, "تحديث متابعة الأجزاء", code=403)
                    self.assertEqual(page.locator('article[id^="part-"]').count(), 0)
                    self.assertNotIn(audio["sha256"], page.content())
                    self.capture(page, "current-scope-revoked", proof)
                    proof.update(
                        explicit_text_only_choice=True,
                        independent_plan_signature=True,
                        original_manifest_sha256=full["manifest_sha256"],
                        original_audio_sha256=sha256(original_audio).hexdigest(),
                        original_parts=3,
                        selected_parts=1,
                        omitted_parts=2,
                        original_audio_unchanged=True,
                        verified_selected_delivery=True,
                        attempts=1,
                        reading_not_claimed=True,
                        revoked_scope_denied=True,
                        external_send=False,
                        keyboard_submit=True,
                        browser_version=browser.version,
                    )
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof["status"] = "PASS"
                finally:
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                    proof["traces"].append("trace.zip")
                    context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2))
        print("FUNCTIONAL_COMPOSITE_CHOICE_BROWSER " + json.dumps(proof, ensure_ascii=False))
