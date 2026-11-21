"""Protected native bounded retry journey with independently signed local evidence."""

import json
import os
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent

from . import test_browser
from .models import CompositeRetry
from .test_retry import FEATURES, RetryFixture

OUT = Path(".local/qa/functional-continuation/composite-retry-browser")


@override_settings(**FEATURES)
class CompositeRetryBrowserTests(RetryFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = test_browser.DeliveryDeskBrowserTests.sync
    click = test_browser.DeliveryDeskBrowserTests.click
    import_part = test_browser.DeliveryDeskBrowserTests.import_part

    def capture(self, page, label, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            filename = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_native_failed_part_fresh_signed_bounded_retry_keeps_original_failure_and_no_duplicates(
        self,
    ):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "traces": [],
            "page_errors": [],
            "external_requests": [],
        }
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    viewport={"width": 320, "height": 900}, accept_downloads=True
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)

                def local_only(route):
                    parsed = urlsplit(route.request.url)
                    if (
                        parsed.scheme != "http"
                        or parsed.netloc != urlsplit(self.live_server_url).netloc
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
                        page.goto(self.live_server_url + "/casework/staff/login/").status, 200
                    )
                    page.locator("#credential").fill("synthetic-credential-with-32-characters")
                    self.click(page, "دخول المكتب")
                    self.click(page, self.a["public_ref"])
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
                    full = self.sync(self.request)
                    original = None
                    failed_parent = None
                    for ordinal in (1, 2, 3):
                        lease = self.sync(self.reserve)
                        part = self.sync(lambda: self.resolve(lease))
                        bundle = self.sync(
                            lambda: self.bundle(
                                lease, part, "FAILED" if ordinal == 3 else "DELIVERED"
                            )
                        )
                        self.click(page, "تحديث متابعة الأجزاء")
                        self.import_part(page, ordinal, bundle)
                        if ordinal == 3:
                            original, failed_parent = part, lease.intent_key
                    self.assertIn("فشل يحتاج مراجعة بشرية", page.locator("#part-3").inner_text())
                    self.assertEqual(page.locator("form[data-retry-export]").count(), 1)
                    self.assertEqual(page.locator("#part-1 form[data-retry-export]").count(), 0)
                    self.assertEqual(page.locator("#part-2 form[data-retry-export]").count(), 0)
                    self.capture(page, "signed-failure", proof)
                    page.get_by_text("مراجعة فشل الجزء 3 وطلب محاولة إضافية", exact=True).click()
                    with page.expect_download() as download:
                        page.get_by_role(
                            "button", name="تنزيل طلب محاولة إضافية للجزء 3", exact=True
                        ).click()
                    request = json.loads(Path(download.value.path()).read_text())
                    self.assertEqual(request["retry"]["root_plan"], full["plan_sha256"])
                    self.assertEqual(request["retry"]["manifest_sha256"], full["manifest_sha256"])
                    self.assertEqual(request["retry"]["part"]["id"], original["id"])
                    self.assertEqual(
                        request["retry"]["part"]["sha256"], sha256(original["raw"]).hexdigest()
                    )
                    self.assertEqual(
                        (request["retry"]["logical_ordinal"], request["retry"]["queue_ordinal"]),
                        (3, 1),
                    )
                    self.assertEqual(len(request["retry"]["full_manifest"]), 3)
                    self.assertEqual(request["retry"]["max_retries"], 3)
                    self.assertNotEqual(request["plan_sha256"], full["plan_sha256"])
                    approval = self.retry_receipt(request)
                    form = page.locator('form[data-retry-stage="3"]')
                    form.locator("textarea").fill(
                        json.dumps(
                            {"request_sha256": request["plan_sha256"], "receipt": asdict(approval)}
                        )
                    )
                    form.locator('[name="confirm"]').check()
                    self.click(page, "تسجيل محاولة إضافية للجزء 3")
                    self.assertEqual(self.sync(lambda: CompositeRetry.objects.count()), 1)
                    self.assertEqual(self.sync(lambda: DeliveryIntent.objects.count()), 4)
                    self.assertEqual(self.sync(lambda: DeliveryAttempt.objects.count()), 3)
                    self.click(page, "تحديث متابعة الأجزاء")
                    lease = self.sync(self.reserve)
                    successor = self.sync(lambda: self.resolve(lease))
                    self.assertEqual((successor["ordinal"], successor["queue_ordinal"]), (3, 1))
                    self.assertEqual(successor["id"], original["id"])
                    self.assertEqual(successor["raw"], original["raw"])
                    self.click(page, "تحديث متابعة الأجزاء")
                    self.import_part(
                        page, 3, self.sync(lambda: self.bundle(lease, successor, "ACCEPTED"))
                    )
                    self.assertFalse(self.sync(self.status)["delivery_verified"])
                    self.assertEqual(page.locator("form[data-retry-export]").count(), 0)
                    self.assertIsNone(self.sync(self.reserve))
                    self.capture(page, "accepted-not-delivered", proof)
                    self.import_part(
                        page, 3, self.sync(lambda: self.bundle(lease, successor, "DELIVERED"))
                    )
                    result = self.sync(self.status)
                    self.assertTrue(result["delivery_verified"])
                    self.assertEqual(result["verified_parts"], 3)
                    self.assertEqual(result["original_plan"]["state"], "PARTIALLY_FAILED")
                    self.assertFalse(result["original_plan"]["delivery_verified"])
                    self.assertIn(
                        "PARTIALLY_FAILED", page.locator("#original-plan-state").inner_text()
                    )
                    self.assertEqual(
                        self.sync(lambda: DeliveryIntent.objects.get(pk=failed_parent).state),
                        "FAILED_REQUIRES_REVIEW",
                    )
                    self.assertEqual(self.sync(lambda: DeliveryAttempt.objects.count()), 4)
                    self.assertIsNone(self.sync(self.reserve))
                    self.assertNotIn(lease.token, page.content())
                    self.capture(page, "verified-current-chain", proof)
                    self.directory.refs = frozenset()
                    self.click(page, "تحديث متابعة الأجزاء", code=403)
                    self.assertEqual(page.locator('article[id^="part-"]').count(), 0)
                    self.assertNotIn(original["sha256"], page.content())
                    self.capture(page, "revoked-current-grant", proof)
                    proof.update(
                        independent_retry_plan=True,
                        fresh_signed_retry_approval=True,
                        signed_failure_required=True,
                        original_logical_ordinal=3,
                        retry_queue_ordinal=1,
                        exact_original_bytes=True,
                        original_sha256=original["sha256"],
                        original_failed_plan_retained=True,
                        accepted_not_delivered=True,
                        effective_verified_parts=3,
                        original_parts=3,
                        retry_rows=1,
                        attempts=4,
                        no_duplicate_delivered_parts=True,
                        max_retries=3,
                        revoked_scope_denied=True,
                        external_send=False,
                        reading_not_claimed=True,
                        keyboard_submit=True,
                        browser_version=browser.version,
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof["status"] = "PASS"
                finally:
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                    proof["traces"].append("trace.zip")
                    context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2))
        print("FUNCTIONAL_COMPOSITE_RETRY_BROWSER " + json.dumps(proof, ensure_ascii=False))
