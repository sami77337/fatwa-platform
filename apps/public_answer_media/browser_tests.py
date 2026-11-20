"""Protected native transcript edits, independent releases and real audio segments."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media import services as answer_media
from apps.casework.models import Case

from .models import PublicMediaAction, PublicMediaEdition, RecordingTranscript, TranscriptAction
from .test_support import CREDENTIALS, FEATURES, TEXT, MediaFixture, audio

OUT = Path(".local/qa/functional-continuation/public-answer-media-browser")
CORRECTED = "تصحيح اصطناعي محفوظ راجعه الشيخ بصورة مستقلة عن النسخة الأولى."


@override_settings(**FEATURES)
class PublicAnswerMediaBrowserTests(MediaFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, function):
        def work():
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as workers:
            return workers.submit(work).result(timeout=30)

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.press("Enter")
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def send(self, page, form):
        self.assertEqual(form.count(), 1)
        self.submit(page, form.locator('button:not([type="button"])'))

    def login(self, page, subject):
        response = page.goto(self.live_server_url + "/casework/staff/login/")
        self.assertEqual(response.status, 200)
        page.locator("#credential").fill(CREDENTIALS[subject])
        self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))

    def open_desk(self, page):
        response = page.goto(self.live_server_url + "/casework/staff/")
        self.assertEqual(response.status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))
        self.submit(page, page.get_by_role("button", name="التسجيل والتفريغ المراجع", exact=True))

    def decision(self, page, kind, identifier, command):
        attribute = "transcript" if kind == "transcript" else "media"
        article = page.locator(f'article[data-{attribute}-id="{identifier}"]')
        form = article.locator(f'form.{kind}-decision[data-command="{command}"]')
        self.assertEqual(form.count(), 1)
        form.locator('[name="note"]').fill("مراجعة مستقلة اصطناعية لهذه النسخة: " + command)
        form.locator('[name="confirmed"]').check()
        if command == "RELEASE":
            form.locator('[name="minutes"]').fill("15")
        self.send(page, form)

    def prepare(self, page, transcript_id, label):
        self.open_desk(page)
        form = page.locator("form.media-prepare")
        form.locator('[name="transcript_id"]').select_option(transcript_id)
        form.locator('[name="label"]').fill(label)
        form.locator('[name="note"]').fill("أذنت صراحة بمراجعة التسجيل والتفريغ المحدد للإتاحة")
        self.send(page, form)
        return page.locator("#media-history article[data-media-id]").last.get_attribute(
            "data-media-id"
        )

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / name), full_page=True)
            proof["screenshots"].append(name)

    def media_state(self, page, *, start=0):
        player = page.locator("audio[controls]").first
        self.assertIsNone(player.get_attribute("autoplay"))
        state = None
        for _ in range(120):
            state = player.evaluate(
                "e => ({ready:e.readyState,time:e.currentTime,duration:e.duration,paused:e.paused,error:e.error?.code || null})"
            )
            if (
                state["ready"] >= 1
                and state["duration"]
                and abs(state["duration"] - 6) < 0.1
                and abs(state["time"] - start) < 0.1
                and state["error"] is None
            ):
                return state
            page.wait_for_timeout(100)
        self.fail(f"actual recording did not load/seek to its bound time: {state!r}")

    def play_segment(self, page):
        initial = self.media_state(page, start=1)
        self.assertTrue(initial["paused"], "entering the segment must not autoplay")
        player = page.locator("audio[controls]").first
        # Real keyboard activation of the native media controls; no injected
        # player, fake clock, changed currentTime or browser security override.
        player.press("Space")
        state = initial
        for _ in range(100):
            state = player.evaluate(
                "e => ({time:e.currentTime,paused:e.paused,error:e.error?.code || null})"
            )
            if state["time"] > 1.15 and not state["paused"] and state["error"] is None:
                player.press("Space")
                return {
                    "initial_time": initial["time"],
                    "playing_time": state["time"],
                    "native_keyboard": True,
                }
            page.wait_for_timeout(50)
        self.fail(f"native control did not play the exact selected original: {state!r}")

    def test_native_transcript_revision_review_public_playback_seek_and_withdrawal(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "traces": [],
            "external_requests": [],
            "page_errors": [],
            "audio_sha256": sha256(audio()).hexdigest(),
            "observed_statuses": {},
        }
        contexts = []
        origin = self.live_server_url
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def local_only(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                            proof["external_requests"].append("blocked")
                            route.abort()
                        else:
                            route.continue_()

                    def page_for(label):
                        context = browser.new_context(viewport={"width": 320, "height": 780})
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    editor, reviewer, publisher, anonymous = [
                        page_for(label) for label in ("editor", "reviewer", "publisher", "public")
                    ]
                    for page, subject in (
                        (editor, "editor"),
                        (reviewer, "other"),
                        (publisher, "publisher"),
                    ):
                        self.login(page, subject)
                    self.open_desk(editor)
                    self.media_state(editor)
                    form = editor.locator("form.transcript-save")
                    form.locator('[name="text"]').fill(TEXT)
                    form.locator('[name="note"]').fill("تصحيح تفريغ اصطناعي بعد الاستماع إلى الأصل")
                    form.locator('[name="quote_0"]').fill(TEXT[:21])
                    form.locator('[name="start_ms_0"]').fill("1000")
                    form.locator('[name="end_ms_0"]').fill("2500")
                    self.send(editor, form)
                    first_id = editor.locator(
                        '#transcript-history article[data-version="1"]'
                    ).get_attribute("data-transcript-id")
                    self.capture(editor, "native-transcript-draft", proof)
                    self.open_desk(reviewer)
                    self.decision(reviewer, "transcript", first_id, "REVIEW")
                    first_media = self.prepare(editor, first_id, "تسجيل الجواب الاصطناعي المراجع")
                    self.open_desk(reviewer)
                    self.decision(reviewer, "media", first_media, "REVIEW")
                    self.open_desk(publisher)
                    self.decision(publisher, "media", first_media, "RELEASE")

                    detail_url = f"/library-preview/editions/{self.publication.pk}/"
                    response = anonymous.goto(origin + detail_url)
                    self.assertEqual(response.status, 200)
                    entry = anonymous.get_by_role(
                        "link", name="فتح التسجيل والتفريغ المراجع", exact=True
                    )
                    self.assertEqual(entry.count(), 1)
                    public_url = entry.get_attribute("href")
                    self.assertEqual(
                        public_url,
                        f"/library-preview/publications/{self.publication.pk}/recordings/",
                    )
                    with (
                        anonymous.expect_response(
                            lambda r: r.url.endswith(f"/recordings/{first_media}/audio/")
                        ) as source_response,
                        anonymous.expect_navigation(
                            wait_until="domcontentloaded"
                        ) as entry_navigation,
                    ):
                        entry.click()
                    response = entry_navigation.value
                    proof["public_entry"] = {
                        "detail_url": detail_url,
                        "clicked_recording_url": public_url,
                    }
                    self.assertEqual(response.status, 200)
                    self.assertEqual(source_response.value.status, 200)
                    self.assertEqual(source_response.value.body(), audio())
                    self.assertNotIn(
                        "private-original",
                        source_response.value.headers.get("content-disposition", ""),
                    )
                    self.assertTrue(self.media_state(anonymous)["paused"])
                    self.assertEqual(anonymous.locator(".reviewed-transcript").inner_text(), TEXT)
                    self.assertNotIn(
                        self.receipt["public_ref"], anonymous.locator("main").inner_text()
                    )
                    self.assertNotIn("PRIVATE", anonymous.locator("main").inner_text())
                    self.capture(anonymous, "public-reviewed-recording", proof)
                    proof["observed_statuses"]["public_audio"] = source_response.value.status
                    response = anonymous.get_by_role("link", name=TEXT[:21], exact=True)
                    with anonymous.expect_navigation(wait_until="domcontentloaded") as navigation:
                        response.click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertIn("#t=1,2.5", anonymous.locator("audio").get_attribute("src"))
                    proof["public_seek"] = self.play_segment(anonymous)
                    self.capture(anonymous, "public-documented-segment", proof)

                    self.open_desk(editor)
                    first = editor.locator(f'article[data-transcript-id="{first_id}"]')
                    with editor.expect_navigation(wait_until="domcontentloaded") as navigation:
                        first.get_by_role("link", name="فتح المقطع الموثق 1", exact=True).click()
                    self.assertEqual(navigation.value.status, 200)
                    proof["staff_seek"] = self.play_segment(editor)
                    self.capture(editor, "staff-original-segment", proof)

                    self.open_desk(editor)
                    form = editor.locator("form.transcript-save")
                    self.assertEqual(form.locator('[name="text"]').input_value(), TEXT)
                    form.locator('[name="text"]').fill(CORRECTED)
                    form.locator('[name="change_kind"]').select_option("MEANING_REVIEW")
                    form.locator('[name="note"]').fill(
                        "تصحيح يمس المعنى؛ يرجع إلى الشيخ للمراجعة المستقلة"
                    )
                    for index in range(6):
                        for key in ("quote", "start_ms", "end_ms"):
                            form.locator(f'[name="{key}_{index}"]').fill("")
                    self.send(editor, form)
                    second_id = editor.locator(
                        '#transcript-history article[data-version="2"]'
                    ).get_attribute("data-transcript-id")
                    self.assertNotEqual(first_id, second_id)
                    self.assertEqual(
                        editor.locator(
                            f'form.media-prepare [name="transcript_id"] option[value="{second_id}"]'
                        ).count(),
                        0,
                    )
                    self.assertIn(
                        TEXT,
                        editor.locator(f'article[data-transcript-id="{first_id}"]').inner_text(),
                    )
                    response = anonymous.goto(origin + public_url)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(anonymous.locator(".reviewed-transcript").inner_text(), TEXT)
                    self.assertNotIn(CORRECTED, anonymous.locator("main").inner_text())
                    self.capture(editor, "new-meaning-revision-unapproved", proof)
                    self.open_desk(reviewer)
                    self.decision(reviewer, "transcript", second_id, "APPROVE_MEANING")
                    second_media = self.prepare(
                        editor, second_id, "التسجيل مع التصحيح المراجع المستقل"
                    )
                    self.open_desk(reviewer)
                    self.decision(reviewer, "media", second_media, "REVIEW")
                    self.open_desk(publisher)
                    self.decision(publisher, "media", second_media, "RELEASE")
                    response = anonymous.goto(origin + public_url)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        anonymous.locator(".reviewed-transcript").inner_text(), CORRECTED
                    )
                    self.assertIn("لا توجد أوقات موثقة", anonymous.locator("main").inner_text())
                    self.media_state(anonymous)
                    self.capture(anonymous, "corrected-public-transcript", proof)
                    self.decision(publisher, "media", second_media, "WITHDRAW")
                    response = anonymous.goto(origin + public_url)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(anonymous.locator("audio").count(), 0)
                    self.assertEqual(
                        anonymous.locator("#published-text").inner_text(), self.publication.body
                    )
                    self.assertNotIn(CORRECTED, anonymous.locator("main").inner_text())
                    self.capture(anonymous, "withdrawn-media-valid-text", proof)
                    response = anonymous.goto(
                        origin + f"/library-preview/recordings/{second_media}/audio/"
                    )
                    self.assertEqual(response.status, 404)
                    proof["observed_statuses"]["withdrawn_audio"] = response.status

                    def observed():
                        case = Case.objects.get(pk=self.receipt["case_id"])
                        first = RecordingTranscript.objects.get(pk=first_id)
                        return (
                            case.revision,
                            case.evidence_version,
                            str(case.approved_answer_id),
                            first.text,
                            RecordingTranscript.objects.count(),
                            TranscriptAction.objects.count(),
                            PublicMediaEdition.objects.count(),
                            PublicMediaAction.objects.count(),
                            sha256(answer_media.raw_for_part(first.part)).hexdigest(),
                        )

                    self.assertEqual(
                        self.sync(observed),
                        (3, 1, self.answer_id, TEXT, 2, 2, 2, 5, proof["audio_sha256"]),
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof["browser_version"] = browser.version
                finally:
                    for label, context in contexts:
                        name = "trace.zip" if label == "editor" else f"trace-{label}.zip"
                        context.tracing.stop(path=str(OUT / name))
                        proof["traces"].append(name)
                        context.close()
                    browser.close()
                proof["status"] = "PASS"
        finally:
            (OUT / "result.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
            )
