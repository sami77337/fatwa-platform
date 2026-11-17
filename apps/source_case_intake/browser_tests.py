"""Real Chromium: source review, separation, attachment and canonical timeline."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from tests.casework.test_http import Directory

from . import services, simulators
from .http_tests import DESK_SETTINGS, receive
from .models import EvidenceBinding

OUT = Path(".local/qa/v10-origin/browser")


@override_settings(**DESK_SETTINGS)
class SourceDeskBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_review_link_split_raw_attachment_and_mobile_timeline(self):
        from playwright.sync_api import sync_playwright

        root = receive(simulators.telegram(document=True))
        held = receive(simulators.telegram(2, parent=1))
        separate = receive(simulators.telegram(3, sender=200, parent=1))
        yt = receive(simulators.youtube(), "youtube")
        web = receive(simulators.website(), "website")
        directory = Directory()
        directory.grant(
            services.REVIEW_SCOPE, root["public_ref"], yt["public_ref"], web["public_ref"]
        )
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
                page = browser.new_page(
                    viewport={"width": 1280, "height": 900}, accept_downloads=True
                )
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(r):
                    if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(r.request.url)
                        r.abort()
                    else:
                        r.continue_()

                page.route("**/*", route)

                def click(name, keyboard=False):
                    button = page.get_by_role("button", name=name, exact=True)
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        if keyboard:
                            button.focus()
                            button.press("Enter")
                        else:
                            button.click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertIn("no-store", navigation.value.headers["cache-control"])

                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(directory.credential)
                click("دخول المكتب")
                self.assertEqual(page.locator("article[data-receipt]").count(), 5)
                click("غير المحسوم", keyboard=True)
                self.assertEqual(page.locator("article[data-receipt]").count(), 2)
                click("فتح الحدث 2 من telegram")
                self.assertEqual(page.locator("#target-case option").count(), 1)
                self.assertNotIn(separate["case_id"] or "not-a-case", page.content())
                with page.expect_download() as download:
                    page.get_by_role("button", name="تنزيل الأصل الخام", exact=True).click()
                self.assertEqual(
                    Path(download.value.path()).read_bytes(), simulators.telegram(2, parent=1)
                )
                page.locator("#followup-token").fill(root["token"])
                page.locator("#followup-note").fill("راجعت المصدر وهو تعقيب للسائل نفسه")
                page.locator('#followup-form [name="confirm"]').check()
                click("تأكيد إلحاق التعقيب", keyboard=True)
                self.assertEqual(
                    page.locator("#resolved-reference").inner_text(), root["public_ref"]
                )
                self.assertNotIn(root["token"], page.content())
                click("غير المحسوم")
                click("فتح الحدث 3 من telegram")
                self.assertEqual(page.locator("#followup-form").count(), 0)
                page.locator("#split-note").fill("هوية سائل أخرى؛ قضية مستقلة")
                page.locator('#split-form [name="confirm"]').check()
                click("تأكيد إنشاء قضية مستقلة")
                self.assertNotIn("rt_", page.content())
                split_ref = page.locator("#resolved-reference").inner_text()
                self.assertNotEqual(split_ref, root["public_ref"])
                self.assertNotIn(split_ref, directory.current.case_keys)
                click("الأحداث المحفوظة")
                click("فتح الحدث 1 من telegram")
                page.locator("#source-file-token").fill(root["token"])
                page.locator("#source-upload-file").set_input_files(
                    {
                        "name": "synthetic.txt",
                        "mimeType": "text/plain",
                        "buffer": b"synthetic source file",
                    }
                )
                page.locator('#source-upload [name="confirm"]').check()
                click("حفظ المرفق وربطه بالأصل")
                click("التسلسل الزمني للقضية")
                self.assertEqual(page.locator("article[data-evidence-version]").count(), 3)
                self.assertIn("synthetic-file-1", page.content())
                file_url = page.get_by_role("link", name="فتح المرفق synthetic.txt").get_attribute(
                    "href"
                )
                file = page.request.get(self.live_server_url + file_url)
                self.assertEqual(file.status, 200)
                self.assertEqual(file.body(), b"synthetic source file")
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_function("document.documentElement.clientWidth === " + str(width))
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.keyboard.press("Tab")
                    self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                    page.screenshot(path=str(OUT / f"timeline-{width}.png"), full_page=True)
                click("الأحداث المحفوظة")
                page.locator("#source-filter").select_option("youtube")
                click("تصفية الأحداث")
                self.assertEqual(page.locator("article[data-receipt]").count(), 1)
                self.assertIn(yt["public_ref"], page.content())
                directory.grant(services.REVIEW_SCOPE)
                denied = page.request.get(self.live_server_url + file_url)
                self.assertEqual(denied.status, 404)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "rtl": True,
                            "widths": [320, 1280],
                            "raw_exact_bytes": True,
                            "human_followup": True,
                            "human_split": True,
                            "timeline_evidence": 3,
                            "real_file_transfer": True,
                            "revoked_file_status": denied.status,
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(
            EvidenceBinding.objects.get(receipt_id=held["receipt_id"]).case_id,
            EvidenceBinding.objects.get(receipt_id=root["receipt_id"]).case_id,
        )
        self.assertEqual(
            EvidenceBinding.objects.get(receipt_id=separate["receipt_id"]).case.public_ref,
            split_ref,
        )
