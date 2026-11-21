"""Protected native link authoring, review and separate requester availability."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.canonical_search import browser_tests as browser_helpers
from apps.casework import services as cases

from .models import AnswerPart
from .test_youtube import FEATURES, LINK, LinkFixture

OUT = Path(".local/qa/functional-continuation/youtube-answer-browser")


@override_settings(**FEATURES)
class YouTubeAnswerBrowserTests(LinkFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_helpers.CanonicalSearchBrowserTests.sync
    form = browser_helpers.CanonicalSearchBrowserTests.form
    submit = browser_helpers.CanonicalSearchBrowserTests.submit

    def capture(self, page, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            filename = f"{name}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_native_external_link_save_approve_release_and_current_requester_access(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "external_requests": [],
            "page_errors": [],
        }
        origin = urlsplit(self.live_server_url).netloc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            def local(route):
                url = urlsplit(route.request.url)
                if url.scheme != "http" or url.netloc != origin:
                    proof["external_requests"].append("blocked")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local)
            page = context.new_page()
            page.on("pageerror", lambda error: proof["page_errors"].append(type(error).__name__))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill(self.directory.credential)
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.submit(page, "answer_media")
                page.locator("#multipart-text").fill("جواب بشري اصطناعي مرتبط بمرجع خارجي")
                page.locator("#youtube-url").fill(LINK["url"])
                page.locator("#youtube-label").fill(LINK["label"])
                page.locator('[name="synthetic_only"]').check()
                self.submit(page, "answer_media_save")
                link = page.locator("a.external-youtube")
                self.assertEqual(link.count(), 1)
                self.assertEqual(
                    link.get_attribute("href"), "https://www.youtube.com/watch?v=aB3dE6gH9_k"
                )
                self.assertEqual(page.locator("iframe, video").count(), 0)
                self.capture(page, "saved-external-reference", proof)
                self.submit(page, "open")
                approve = self.form(page, "approve")
                for checkbox in approve.locator('input[type="checkbox"]').all():
                    checkbox.check()
                self.submit(page, "approve", form=approve)
                self.submit(page, "answer_media")
                release = self.form(page, "answer_media_release")
                release.locator('[name="confirm"]').check()
                self.submit(page, "answer_media_release", form=release)
                self.capture(page, "separate-private-release", proof)
                page.goto(self.live_server_url + "/casework/status/")
                page.locator('[name="token"]').fill(self.receipt["token"])
                self.submit(page, "unlock", code=200)
                self.submit(page, "answer_media")
                self.assertEqual(
                    page.locator("a.external-youtube").get_attribute("href"),
                    "https://www.youtube.com/watch?v=aB3dE6gH9_k",
                )
                self.capture(page, "current-requester-reference", proof)
                part = self.sync(lambda: str(AnswerPart.objects.get(kind="YOUTUBE_LINK").pk))
                raw = context.request.get(
                    self.live_server_url + f"/casework/status/answer-media/{part}/"
                )
                self.assertEqual(raw.status, 200)
                self.assertEqual(raw.body(), LINK["url"].encode())
                self.sync(lambda: cases.revoke_access(**self.common, requester_id="requester-one"))
                denied = context.request.get(
                    self.live_server_url + f"/casework/status/answer-media/{part}/"
                )
                self.assertNotEqual(denied.status, 200)
                self.assertNotEqual(denied.body(), LINK["url"].encode())
                self.assertEqual(proof["external_requests"], [])
                self.assertEqual(proof["page_errors"], [])
                proof.update(
                    status="PASS",
                    exact_original_uri=True,
                    derived_https_link=True,
                    no_external_fetch=True,
                    separate_approval_and_private_release=True,
                    current_requester_revocation=True,
                )
                (OUT / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
