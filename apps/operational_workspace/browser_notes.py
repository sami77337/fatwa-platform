"""Protected native note creation under the real organizer role; requester isolation."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from . import browser_tests
from .notes_test_support import NOTE_FEATURES, NoteFixture
from .test_support import CREDENTIALS

OUT = Path(".local/qa/functional-continuation/operational-notes-browser")


@override_settings(**NOTE_FEATURES)
class OperationalNotesBrowserTests(NoteFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_organizer_notes_preserve_source_and_remain_hidden_from_requester(self):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.skipTest("protected browser sandbox required")
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER") or None,
                headless=True,
                chromium_sandbox=True,
            )
            context = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
            requester_context = browser.new_context(
                locale="ar", viewport={"width": 1280, "height": 900}
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            requester_context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page, requester = context.new_page(), requester_context.new_page()
            for surface in (page, requester):
                surface.on("pageerror", lambda error: errors.append(str(error)))
                surface.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if urlsplit(request.url).hostname not in {"127.0.0.1", "localhost"}
                        else None
                    ),
                )
            try:
                base = self.live_server_url + "/casework/operations/"
                self.assertEqual(page.goto(base + "login/").status, 200)
                page.locator('[name="credential"]').fill(CREDENTIALS["operator"])
                self.submit(page, page.locator("#ops-login button"))
                row = page.locator(f'article[data-case-ref="{self.target["public_ref"]}"]')
                self.submit(page, row.locator(".ops-notes-open button"))
                self.assertIn("ORGANIZER", page.locator("#ops-actor").inner_text())
                self.assertEqual(page.locator("#ops-note-history > article").count(), 1)
                text = "ملاحظة تشغيلية خاصة بالسؤال\nتصحيح لاحق مستقل <script>لا ينفذ</script>"
                page.locator('[name="note"]').fill(text)
                self.submit(page, page.locator("#ops-note-add button"))
                self.assertEqual(page.locator("#ops-note-saved").count(), 1)
                self.assertEqual(page.locator("#ops-note-history > article").count(), 2)
                self.assertIn(text, page.locator("#ops-note-history").inner_text())
                self.assertEqual(page.locator('script, [name="tags"], [name="answer"]').count(), 0)
                self.screenshots(page, "saved-native-organizer-note")

                self.assertEqual(
                    requester.goto(self.live_server_url + "/casework/status/").status, 200
                )
                requester.locator('[name="token"]').fill(self.target["token"])
                self.submit(requester, requester.locator('form:has([name="token"]) button'))
                body = requester.locator("body").inner_text()
                self.assertIn(self.target["public_ref"], body)
                self.assertNotIn("ملاحظة تشغيلية خاصة", body)
                self.assertNotIn("ملاحظة داخلية لا تعرضها قائمة التشغيل", body)
                self.screenshots(requester, "requester-without-internal-notes")

                self.sync(lambda: self.authority.revoke(action="READ_INTERNAL_NOTES"))
                self.submit(page, page.locator("#ops-back button"))
                row = page.locator(f'article[data-case-ref="{self.target["public_ref"]}"]')
                self.submit(page, row.locator(".ops-notes-open button"))
                self.assertEqual(page.locator("#ops-note-history").count(), 0)
                self.assertEqual(page.locator("#ops-note-add").count(), 1)
                self.assertNotIn("ملاحظة تشغيلية خاصة", page.locator("body").inner_text())
                page.locator('[name="note"]').fill("إضافة بعد سحب الإذن يجب أن ترفض")
                self.sync(lambda: self.authority.revoke(action="ADD_INTERNAL_NOTE"))
                self.submit(page, page.locator("#ops-note-add button"), expected=409)
                self.assertEqual(self.sync(self.immutable_state), self.note_originals)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                context.tracing.stop(path=str(OUT / "trace.zip"))
                requester_context.tracing.stop(path=str(OUT / "requester-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_role": "ORGANIZER",
                            "note_count": 2,
                            "requester_note_disclosure": False,
                            "checks": [
                                "native organizer login and actual append-only internal note form",
                                "literal escaped text and immutable note history",
                                "requester native status excludes both old and new internal notes",
                                "read and add rights independent and current through native submit",
                                "source evidence approved answer and non-note metadata unchanged",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                if not (OUT / "trace.zip").exists():
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                if not (OUT / "requester-trace.zip").exists():
                    requester_context.tracing.stop(path=str(OUT / "requester-trace.zip"))
                requester_context.close()
                context.close()
                browser.close()
