"""Real loopback browser: proposed audio review, confirmation, opening and withdrawal."""

import os

from django.test import LiveServerTestCase, override_settings

from .models import TimedCitation
from .tests import SETTINGS, Fixture


@override_settings(**SETTINGS)
class TimedBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_native_audio_locator_and_withdrawal(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/usr/bin/chromium",
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
            )
            try:
                context = browser.new_context(viewport={"width": 360, "height": 900})
                page = context.new_page()
                external, errors = [], []
                page.on(
                    "request",
                    lambda r: (
                        external.append(r.url)
                        if not r.url.startswith(self.live_server_url + "/")
                        else None
                    ),
                )
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator('[name="credential"]').fill(
                    "synthetic-editor-credential-32-characters"
                )
                page.get_by_role("button", name="دخول المكتب", exact=True).click()
                with page.expect_navigation():
                    page.evaluate(
                        """fields => {
                        const f=document.createElement('form'); f.method='POST';f.action='/casework/staff/';
                        fields.csrfmiddlewaretoken=document.querySelector('[name=csrfmiddlewaretoken]').value;
                        for(const [k,v] of Object.entries(fields)){const i=document.createElement('input');i.name=k;i.value=v;f.appendChild(i);}
                        document.body.appendChild(f);f.submit();
                    }""",
                        {"action": "timed_desk", "case_ref": self.receipt["public_ref"]},
                    )
                page.locator('[name="start_ms"]').fill("10")
                page.locator('[name="end_ms"]').fill("90")
                page.locator('[name="reason"]').fill("Human synthetic locator")
                page.get_by_role("button", name="حفظ اقتراح بشري", exact=True).click()
                page.locator('[name="context_ms"]').select_option("1000")
                page.get_by_role(
                    "button", name="استماع خاص للمراجعة قبل التأكيد", exact=True
                ).click()
                audio = page.locator("audio")
                self.assertIn("review-audio/#t=0,0.1", audio.get_attribute("src"))
                audio.evaluate("""el => new Promise((resolve, reject) => {
                    const timer = setTimeout(() => reject(new Error('audio metadata timeout')), 6000);
                    el.addEventListener('loadedmetadata', () => {clearTimeout(timer); resolve();}, {once:true});
                    el.addEventListener('error', () => {clearTimeout(timer); reject(new Error('audio load failed'));}, {once:true});
                    el.load();
                })""")
                self.assertAlmostEqual(audio.evaluate("el => el.duration"), 0.1, places=2)
                page.get_by_role(
                    "button", name="تأكيد الموضع بعد الاستماع البشري", exact=True
                ).click()
                page.get_by_role("button", name="فتح الموضع المصرح به", exact=True).click()
                audio_url = page.locator("audio").get_attribute("src").split("#")[0]
                response = context.request.get(self.live_server_url + audio_url)
                self.assertEqual(response.body(), self.audio["raw"])
                self.assertIn("no-store", response.headers["cache-control"])
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                page.keyboard.press("Tab")
                self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                page.get_by_role("button", name="سحب الإحالة", exact=True).click()
                self.assertEqual(context.request.get(self.live_server_url + audio_url).status, 404)
                self.assertIn("WITHDRAWN", page.content())
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                print(
                    f"TIMED_BROWSER={browser.version}; sandbox={os.environ.get('FATWA_TEST_BROWSER_NO_SANDBOX') != '1'}; native duration=0.1; withdrawal=404"
                )
            finally:
                browser.close()

        self.assertEqual(TimedCitation.objects.count(), 1)
        row = TimedCitation.objects.get()
        self.assertEqual((row.start_ms, row.end_ms), (10, 90))
