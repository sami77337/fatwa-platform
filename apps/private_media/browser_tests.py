"""Protected Chromium proof of native signed-link playback and downloads.

These journeys retain real browser security and use current synthetic sessions.
API requests supplement native controls to prove HEAD/Range denial after a grant
is withdrawn; they do not replace navigation, media decoding or native downloads.
"""

import json
import os
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.public_answer_media import browser_tests as recording_browser
from apps.public_answer_media.test_support import FEATURES as RECORDING_FEATURES
from apps.public_answer_media.test_support import MediaFixture, audio
from apps.research_library import browser_tests as library_browser
from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture, payload

from . import links
from .test_signed_links import FEATURES, LINK_SETTINGS, PrivateOriginalFixture

OUT = Path(".local/qa/functional-continuation/private-media-links-browser")


def signed_features(base):
    middleware = base["MIDDLEWARE"]
    name = "apps.private_media.links.PrivateMediaResponses"
    return {
        **base,
        **LINK_SETTINGS,
        "MIDDLEWARE": [name, *[item for item in middleware if item != name]],
    }


class NativeLinks:
    host = "127.0.0.1"
    sync = recording_browser.PublicAnswerMediaBrowserTests.sync
    submit = recording_browser.PublicAnswerMediaBrowserTests.submit
    send = recording_browser.PublicAnswerMediaBrowserTests.send

    @contextmanager
    def browser(self, label):
        from playwright.sync_api import sync_playwright

        folder = OUT / label
        folder.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "screenshots": [],
            "traces": [],
            "external_requests": [],
            "page_errors": [],
            "media_statuses": [],
            "widths": [320, 1280],
        }
        contexts, media = [], []
        self.folder, self.proof, self.media_responses = folder, proof, media
        origin = self.live_server_url

        def local_only(route):
            target = urlsplit(route.request.url)
            if target.scheme != "http" or target.netloc != urlsplit(origin).netloc:
                proof["external_requests"].append("blocked")
                route.abort()
            else:
                route.continue_()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def page_for(name):
                        context = browser.new_context(
                            viewport={"width": 320, "height": 900}, accept_downloads=True
                        )
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((name, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )

                        def response_seen(response):
                            if links.route(urlsplit(response.url).path) is not None:
                                media.append((response.url, response.status))
                                proof["media_statuses"].append(response.status)

                        page.on("response", response_seen)
                        return page

                    yield page_for
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    self.assertTrue(any(status in {200, 206} for _, status in media))
                    proof["status"] = "PASS"
                finally:
                    for name, context in contexts:
                        filename = "trace-" + name + ".zip"
                        context.tracing.stop(path=str(folder / filename))
                        proof["traces"].append(filename)
                        context.close()
                    browser.close()
        finally:
            (folder / "result.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
            )

    def login_native(self, page, credential):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
        page.locator("#credential").fill(credential)
        self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))

    def open_case(self, page):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))

    def open_action(self, page, action):
        self.send(page, page.locator(f'form:has(input[name="action"][value="{action}"])'))

    def unlock(self, page):
        self.assertEqual(page.goto(self.live_server_url + "/casework/status/").status, 200)
        if page.locator("#portal-token").count():
            page.locator("#portal-token").fill(self.receipt["token"])
            button = "فتح قضيتي"
        else:
            page.locator("#workspace-token").fill(self.receipt["token"])
            button = "فتح المتابعة الخاصة"
        self.submit(page, page.get_by_role("button", name=button, exact=True))

    def ticket(self, value):
        parsed = urlsplit(value)
        self.assertEqual((parsed.scheme, parsed.netloc), ("", ""))
        self.assertIsNotNone(links.route(parsed.path))
        self.assertEqual(set(parse_qs(parsed.query)), {"access"})
        self.assertLessEqual(len(value), 2048)
        return self.live_server_url + value

    def decoded_audio(self, page, *, selector="audio[controls]", play=True):
        player = page.locator(selector).first
        self.assertTrue(player.is_visible())
        self.assertIsNone(player.get_attribute("autoplay"))
        self.assertGreaterEqual(player.bounding_box()["height"], 40)
        if play:
            # preload=none is intentional. Real keyboard activation must start
            # the native control; do not inject play() or change currentTime.
            player.press("Space")
        page.wait_for_function(
            """({selector, play}) => {
            const media = document.querySelector(selector);
            return media && media.readyState >= 1 && Number.isFinite(media.duration)
                && media.duration > 0 && !media.error && (!play || media.played.length > 0);
        }""",
            arg={"selector": selector, "play": play},
        )
        if play:
            state = player.evaluate(
                "e => ({duration:e.duration,time:e.currentTime,paused:e.paused})"
            )
            if not state["paused"]:
                player.press("Space")
            self.proof.setdefault("native_playbacks", []).append({"selector": selector, **state})
        url = self.ticket(player.get_attribute("src"))
        self.assertTrue(
            any(
                seen.split("#")[0] == url.split("#")[0] and status in {200, 206}
                for seen, status in self.media_responses
            )
        )
        return url

    def reads(self, page, url, raw):
        response = page.context.request.get(url, headers={"Range": "bytes=8-23"})
        self.assertEqual(response.status, 206)
        self.assertEqual(response.body(), raw[8:24])
        self.assertEqual(response.headers["content-range"], f"bytes 8-23/{len(raw)}")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("no-store", response.headers["cache-control"])
        head = page.context.request.head(url)
        self.assertEqual(head.status, 200)
        self.assertEqual(head.body(), b"")
        self.assertEqual(int(head.headers["content-length"]), len(raw))

    def refused(self, page, url, raw):
        for method in (page.context.request.get, page.context.request.head):
            response = method(url, headers={"Range": "bytes=8-23"})
            self.assertEqual(response.status, 404)
            self.assertNotIn(raw, response.body())
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            for name in ("content-range", "content-disposition", "etag", "x-content-sha256"):
                self.assertNotIn(name, response.headers)

    def capture(self, page, label):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(self.folder / name), full_page=True)
            self.proof["screenshots"].append(name)

    def download_native(self, page, button, raw):
        with page.expect_download() as waiting:
            button.click()
        download = waiting.value
        self.assertIsNone(download.failure())
        destination = self.folder / "authorized-download.bin"
        download.save_as(str(destination))
        self.assertEqual(destination.read_bytes(), raw)


@override_settings(**signed_features(FEATURES))
class PrivateOriginalLinksBrowserTests(NativeLinks, PrivateOriginalFixture, LiveServerTestCase):
    def test_native_requester_and_staff_media_urls_downloads_and_browser_isolation(self):
        original = self.originals()
        with self.browser("originals") as page_for:
            requester, staff, other = (
                page_for(name) for name in ("requester", "staff", "other-browser")
            )
            self.unlock(requester)
            self.open_action(requester, "answer_media")
            answer = self.decoded_audio(requester)
            self.reads(requester, answer, self.raw)
            self.capture(requester, "requester-answer")
            self.assertEqual(requester.goto(self.live_server_url + "/casework/status/").status, 200)
            self.open_action(requester, "attachments")
            self.submit(
                requester,
                requester.get_by_role("button", name="معاينة private-question.wav", exact=True),
            )
            attachment = self.decoded_audio(requester)
            self.reads(requester, attachment, self.raw)
            self.download_native(
                requester,
                requester.get_by_role(
                    "button", name="تنزيل الأصل private-question.wav", exact=True
                ),
                self.raw,
            )
            self.capture(requester, "requester-attachment")
            with self.settings(
                FATWA_REQUESTER_PORTAL_ENABLED=True,
                FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED=True,
            ):
                self.assertEqual(
                    requester.goto(self.live_server_url + "/casework/status/").status, 200
                )
                self.assertTrue(
                    requester.get_by_role(
                        "heading", name="بوابة السائل الخاصة", exact=True
                    ).is_visible()
                )
                portal_answer = self.decoded_audio(requester, selector="#answer audio[controls]")
                portal_attachment = self.decoded_audio(
                    requester, selector="#attachments audio[controls]"
                )
                for url in (portal_answer, portal_attachment):
                    self.reads(requester, url, self.raw)
                for label in ("تنزيل جزء الجواب 2", "تنزيل المرفق 1"):
                    button = requester.get_by_role("link", name=label, exact=True)
                    download = self.ticket(button.get_attribute("href"))
                    self.assertNotIn(download, (portal_answer, portal_attachment))
                    self.download_native(requester, button, self.raw)
                self.capture(requester, "requester-portal-originals")
                self.unlock(other)
                for url in (answer, attachment, portal_answer, portal_attachment):
                    self.refused(other, url, self.raw)
            self.login_native(staff, self.directory.credential)
            self.open_case(staff)
            self.open_action(staff, "answer_media")
            staff_answer = self.decoded_audio(staff)
            self.reads(staff, staff_answer, self.raw)
            self.capture(staff, "staff-answer")
            self.refused(staff, answer, self.raw)
            self.assertEqual(self.sync(self.originals), original)
            self.proof.update(
                native_requester_attachment=True,
                native_answer_parts=True,
                native_private_download=True,
                native_requester_portal=True,
                portal_signed_audio_and_downloads=True,
                same_actor_new_browser_denied=True,
                audience_substitution_denied=True,
                head_and_range_authorized=True,
                exact_original_sha256=sha256(self.raw).hexdigest(),
                originals_unchanged=True,
            )


@override_settings(**signed_features(LIBRARY_FEATURES))
class PrivateLibraryLinksBrowserTests(NativeLinks, LibraryFixture, LiveServerTestCase):
    def test_native_library_playback_download_and_current_download_revocation(self):
        raw = audio()
        record = self.approve(
            self.write(
                payload=payload(kind="AUDIO"),
                file_bytes=raw,
                filename="private-library.wav",
                media_type="audio/wav",
            ),
            uses=["READ", "DOWNLOAD"],
        )
        with self.browser("library") as page_for:
            page, other = page_for("reader"), page_for("other-browser")
            self.login_native(page, library_browser.CREDENTIALS["editor"])
            self.open_case(page)
            self.open_action(page, "rl_open")
            self.submit(page, page.get_by_role("button", name="فتح المادة ونسخها", exact=True))
            self.assertEqual(
                page.locator("#library-selected").get_attribute("data-library-version"),
                record["version_id"],
            )
            inline = self.decoded_audio(page)
            self.reads(page, inline, raw)
            button = page.get_by_role("link", name="تنزيل الملف المصرح به", exact=True)
            download = self.ticket(button.get_attribute("href"))
            self.assertNotEqual(inline, download)
            self.download_native(page, button, raw)
            self.capture(page, "library-original")
            self.login_native(other, library_browser.CREDENTIALS["editor"])
            self.refused(other, inline, raw)
            self.authority.denied.add("DOWNLOAD")
            self.refused(page, download, raw)
            self.reads(page, inline, raw)
            self.proof.update(
                native_library_playback=True,
                native_library_download=True,
                exact_version=True,
                download_revocation_does_not_revoke_read=True,
                copied_url_denied=True,
                exact_original_sha256=sha256(raw).hexdigest(),
            )


@override_settings(**signed_features(RECORDING_FEATURES))
class PrivateRecordingLinksBrowserTests(NativeLinks, MediaFixture, LiveServerTestCase):
    media_state = recording_browser.PublicAnswerMediaBrowserTests.media_state
    play_segment = recording_browser.PublicAnswerMediaBrowserTests.play_segment

    def test_native_recording_and_reviewed_segment_playback_then_current_rights_denial(self):
        record = self.review(self.save())
        with self.browser("recordings") as page_for:
            page = page_for("editor")
            self.login_native(page, recording_browser.CREDENTIALS["editor"])
            self.open_case(page)
            self.open_action(page, "pm_open")
            original = self.decoded_audio(page)
            self.reads(page, original, audio())
            article = page.locator(f'article[data-transcript-id="{record["id"]}"]')
            self.submit(page, article.get_by_role("link", name="فتح المقطع الموثق 1", exact=True))
            segment = self.decoded_audio(page, play=False)
            self.assertEqual(urlsplit(segment).fragment, "t=1,2.5")
            self.proof["segment_playback"] = self.play_segment(page)
            self.reads(page, segment, audio())
            self.capture(page, "reviewed-segment")
            self.authority.denied.add("READ_TRANSCRIPT")
            self.refused(page, original, audio())
            self.refused(page, segment, audio())
            self.proof.update(
                native_recording_playback=True,
                reviewed_segment_preserved=True,
                every_range_reauthorized=True,
                head_reauthorized=True,
                exact_original_sha256=sha256(audio()).hexdigest(),
            )
