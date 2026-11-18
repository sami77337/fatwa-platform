"""Real integrated HTML/JS, sandbox Chromium and synthetic microphone only."""

import os

from apps.browser_audio import test_browser as fixtures
from django.test import LiveServerTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from config.settings.campaign_review import MIDDLEWARE


@override_settings(
    **{**fixtures.FEATURES, "ROOT_URLCONF": "config.campaign_urls", "MIDDLEWARE": MIDDLEWARE}
)
class RecorderExternalReview(LiveServerTestCase):
    host = "127.0.0.1"
    setUp = fixtures.BrowserAudioTests.setUp
    browser = fixtures.BrowserAudioTests.browser
    context = fixtures.BrowserAudioTests.context
    requester = fixtures.BrowserAudioTests.requester
    click = fixtures.BrowserAudioTests.click
    released = fixtures.BrowserAudioTests.released
    sync = fixtures.BrowserAudioTests.sync

    def test_native_preview_requires_acceptance_and_cancel_releases_late_permission(self):
        from playwright.sync_api import sync_playwright

        self.assertEqual(os.environ.get("FATWA_BROWSER_SANDBOX", "1"), "1")
        with sync_playwright() as driver:
            browser = self.browser(driver)
            try:
                page = self.requester(browser)
                recorder = fixtures.recorder(page)
                field = recorder.locator("xpath=ancestor::form").locator('input[type="file"]')
                self.assertEqual(page.evaluate("probe.calls"), 0)
                writes = []
                page.on(
                    "request", lambda req: writes.append(req.url) if req.method == "POST" else None
                )
                recorder.locator("[data-audio-start]").click()
                page.wait_for_function(
                    "() => [...document.querySelectorAll('[data-browser-audio]')].some(r => +r.dataset.audioFrames > 512)"
                )
                recorder.locator("[data-audio-stop]").click()
                self.assertEqual(recorder.get_attribute("data-audio-state"), "preview")
                self.assertEqual(field.evaluate("e => e.files.length"), 0)
                self.released(page)
                blocked = recorder.evaluate(
                    "r => !r.closest('form').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
                )
                self.assertTrue(blocked)
                recorder.locator("[data-audio-accept]").click()
                self.assertEqual(field.evaluate("e => e.files.length"), 1)
                self.assertEqual(field.evaluate("e => e.files[0].type"), "audio/wav")
                self.assertEqual(writes, [])
                recorder.locator("[data-audio-cancel]").click()
                self.assertEqual(field.evaluate("e => e.files.length"), 0)
                self.assertEqual(page.evaluate("probe.urls.size"), 0)

                # Hold the actual synthetic device promise across cancellation.
                page.evaluate("""() => {
                  const native = navigator.mediaDevices.getUserMedia;
                  navigator.mediaDevices.getUserMedia = async (...args) => {
                    const stream = await native(...args);
                    await new Promise(resolve => window.releaseLate = resolve);
                    return stream;
                  };
                }""")
                recorder.locator("[data-audio-start]").click()
                page.wait_for_function("() => typeof releaseLate === 'function'")
                recorder.locator("[data-audio-cancel]").click()
                page.evaluate("releaseLate()")
                self.released(page)
                self.assertEqual(field.evaluate("e => e.files.length"), 0)
                self.assertEqual(self.sync(lambda: CaseAttachment.objects.count()), 0)
                self.assertEqual(writes, [])
                self.assertEqual(self.external, [])
                # Fixed JS assets do not opt themselves into microphone HTML CSP.
                asset = page.request.get(self.live_server_url + "/casework/audio-capture.js")
                self.assertEqual(asset.status, 200)
                self.assertIn("no-store", asset.headers["cache-control"])
                self.assertNotIn("microphone=(self)", asset.headers.get("permissions-policy", ""))
                self.assertNotIn("'unsafe-inline'", asset.headers["content-security-policy"])
            finally:
                browser.close()
