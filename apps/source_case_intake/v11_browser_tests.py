"""V11 browser-operated source simulation, held review, return context and audio."""

import io
import json
import os
import wave
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from tests.casework.test_http import Directory

from . import services, simulators
from .http_tests import receive
from .models import SourceReceipt, SourceReviewNote
from .v11_tests import V11_SETTINGS


@override_settings(**V11_SETTINGS)
class V11SourceBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_browser_simulate_hold_reopen_followup_search_return_and_audio(self):
        from playwright.sync_api import sync_playwright

        raw = json.loads(simulators.telegram(document=True))
        raw["message"]["document"].update(file_name="synthetic.wav", mime_type="audio/wav")
        root = receive(simulators.raw(raw))
        directory = Directory()
        directory.grant(services.REVIEW_SCOPE, root["public_ref"])
        audio = io.BytesIO()
        with wave.open(audio, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b"\x00\x00" * 800)
        errors, external = [], []
        output = Path(".local/qa/v11-source/browser")
        output.mkdir(parents=True, exist_ok=True)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory), sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(r):
                    if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(r.request.url)
                        r.abort()
                    else:
                        r.continue_()

                page.route("**/*", route)

                def click(name, keyboard=False):
                    button = page.get_by_role("button", name=name, exact=True)
                    with page.expect_navigation(wait_until="domcontentloaded") as nav:
                        if keyboard:
                            button.focus()
                            button.press("Enter")
                        else:
                            button.click()
                    self.assertEqual(nav.value.status, 200)
                    self.assertIn("no-store", nav.value.headers["cache-control"])

                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(directory.credential)
                click("دخول المكتب")
                page.locator("#source-query").fill(root["public_ref"])
                click("تصفية الأحداث")
                click("فتح الحدث 1 من telegram")
                page.locator('#source-simulator [name="confirm"]').check()
                click("استقبال الحدث الاصطناعي", keyboard=True)
                generated_id = page.locator('#source-note [name="receipt_id"]').input_value()
                self.assertEqual(page.locator("#followup-form").count(), 1)
                page.locator("#note-kind").select_option("HOLD")
                page.locator("#review-note").fill("تأجيل حتى التحقق من سياق الرسالة")
                page.locator('#source-note [name="confirm"]').check()
                click("حفظ المتابعة البشرية")
                self.assertEqual(page.locator("#followup-form").count(), 0)
                self.assertIn("أُجّلت المراجعة", page.content())
                page.locator("#note-kind").select_option("REOPEN")
                page.locator("#review-note").fill("تحقق بشري؛ أعيد فتح المراجعة")
                page.locator('#source-note [name="confirm"]').check()
                click("حفظ المتابعة البشرية", keyboard=True)
                page.locator("#followup-token").fill(root["token"])
                page.locator("#followup-note").fill("إلحاق بعد مراجعة الأصل وملاحظات المتابعة")
                page.locator('#followup-form [name="confirm"]').check()
                click("تأكيد إلحاق التعقيب")
                click("العودة إلى نتائج البحث")
                self.assertEqual(page.locator("#source-query").input_value(), root["public_ref"])
                click("فتح الحدث 1 من telegram")
                page.locator("#source-file-token").fill(root["token"])
                page.locator("#source-upload-file").set_input_files(
                    {"name": "synthetic.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
                )
                page.locator('#source-upload [name="confirm"]').check()
                click("حفظ المرفق وربطه بالأصل")
                click("التسلسل الزمني للقضية")
                self.assertEqual(page.locator("article[data-evidence-version]").count(), 3)
                media = page.locator("audio")
                media.evaluate("element => element.play()")
                page.wait_for_function("document.querySelector('audio').duration > 0")
                self.assertAlmostEqual(media.evaluate("element => element.duration"), 0.1, places=2)
                media_url = media.get_attribute("src")
                self.assertEqual(
                    page.request.get(self.live_server_url + media_url).body(), audio.getvalue()
                )
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_function("document.documentElement.clientWidth === " + str(width))
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(output / f"timeline-{width}.png"), full_page=True)
                directory.grant(services.REVIEW_SCOPE)
                self.assertEqual(page.request.get(self.live_server_url + media_url).status, 404)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (output / "result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "browser_simulator": True,
                            "hold_reopen": True,
                            "followup_after_review": True,
                            "search_return": True,
                            "audio_duration": 0.1,
                            "audio_bytes_exact": True,
                            "revoked_media": 404,
                            "rtl_widths": [320, 1280],
                            "external_requests": external,
                            "page_errors": errors,
                        },
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(SourceReceipt.objects.count(), 2)
        self.assertEqual(
            list(
                SourceReviewNote.objects.filter(receipt_id=generated_id)
                .order_by("sequence")
                .values_list("kind", flat=True)
            ),
            ["HOLD", "REOPEN"],
        )
