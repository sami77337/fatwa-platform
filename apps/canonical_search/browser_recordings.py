"""Protected real search result to exact reviewed recording, without browser bypasses."""

import json
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.public_answer_media import browser_tests as media_browser
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction
from apps.public_answer_media.test_support import TEXT, audio

from . import browser_tests as search_browser
from .test_recordings import FEATURES, RecordingFixture

OUT = Path(".local/qa/functional-continuation/search-recording-browser")


@override_settings(**FEATURES)
class RecordingSearchBrowserTests(RecordingFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = search_browser.CanonicalSearchBrowserTests.sync
    form = search_browser.CanonicalSearchBrowserTests.form
    submit = search_browser.CanonicalSearchBrowserTests.submit
    media_state = media_browser.PublicAnswerMediaBrowserTests.media_state
    play_segment = media_browser.PublicAnswerMediaBrowserTests.play_segment

    def capture(self, page, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            filename = f"{name}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            proof["screenshots"].append(filename)

    def test_actual_fts_result_opens_reviewed_original_at_pinned_segment(self):
        from playwright.sync_api import sync_playwright

        transcript = self.reviewed()
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "page_errors": [],
            "external_requests": [],
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

            def local_only(route):
                url = urlsplit(route.request.url)
                if url.scheme != "http" or url.netloc != origin:
                    proof["external_requests"].append("blocked")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local_only)
            page = context.new_page()
            page.on("pageerror", lambda error: proof["page_errors"].append(type(error).__name__))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.submit(page, "cs_open")
                self.submit(page, "cs_rebuild")
                page.locator("#canonical-query").fill("تفريغ")
                page.locator("#canonical-mode").select_option("FTS")
                page.locator("#canonical-kind").select_option("RECORDING_TRANSCRIPT")
                self.submit(page, "cs_search")
                hit = page.locator('.canonical-hit[data-kind="RECORDING_TRANSCRIPT"]')
                self.assertEqual(hit.count(), 1)
                self.assertEqual(hit.locator("blockquote").text_content(), TEXT[:21])
                segment_url = (
                    f"/casework/staff/recording-transcripts/{transcript['id']}/segments/0/"
                )
                self.assertEqual(hit.locator("a.recording-seek").get_attribute("href"), segment_url)
                self.capture(page, "actual-search-hit", proof)
                with page.expect_navigation(wait_until="domcontentloaded") as opened:
                    hit.locator("a.recording-seek").press("Enter")
                self.assertEqual(opened.value.status, 200)
                self.assertIn("no-store", opened.value.headers.get("cache-control", ""))
                self.assertEqual(page.locator("#segment-text").text_content(), TEXT[:21])
                player = page.locator("audio[controls]")
                audio_url = f"/casework/staff/recording-transcripts/{transcript['id']}/audio/"
                self.assertEqual(player.get_attribute("src"), audio_url + "#t=1,2.5")
                playback = self.play_segment(page)
                self.capture(page, "bound-recording-seek", proof)
                raw = context.request.get(self.live_server_url + audio_url)
                self.assertEqual(raw.status, 200)
                self.assertEqual(raw.body(), audio())
                self.authority.denied.add("READ_TRANSCRIPT")
                refused = page.reload(wait_until="domcontentloaded")
                self.assertNotEqual(refused.status, 200)
                self.assertEqual(page.locator("audio").count(), 0)
                self.assertNotIn(TEXT[:21], page.locator("body").inner_text())
                denied_raw = context.request.get(self.live_server_url + audio_url)
                self.assertNotEqual(denied_raw.status, 200)
                self.assertNotEqual(denied_raw.body(), audio())
                self.assertEqual(self.sync(lambda: RecordingTranscript.objects.count()), 1)
                self.assertEqual(self.sync(lambda: TranscriptAction.objects.count()), 1)
                self.assertEqual(proof["external_requests"], [])
                self.assertEqual(proof["page_errors"], [])
                proof.update(
                    status="PASS",
                    native_fts_result=True,
                    exact_transcript_id=transcript["id"],
                    exact_part_id=str(self.part.pk),
                    exact_original_sha256=sha256(audio()).hexdigest(),
                    start_ms=1000,
                    end_ms=2500,
                    actual_native_playback=playback,
                    current_revocation_denied=True,
                    source_and_review_unchanged=True,
                )
                (OUT / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
