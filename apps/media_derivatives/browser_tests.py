"""Protected native queue, actual local decoding, preserved originals and denials."""

import faulthandler
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseEvidence
from apps.staff_sessions.models import Session
from config.settings import campaign_review

from . import execution
from . import test_http as native
from .models import DerivativeJob, DerivedOutput
from .test_execution import picture
from .test_support import DerivativeFixture
from .views import BASE

OUT = Path(".local/qa/functional-continuation/media-derivatives-browser")
FEATURES = {
    **native.NATIVE,
    "FATWA_STAFF_SESSIONS_ENABLED": True,
    "FATWA_STAFF_MFA_ENABLED": False,
    "FATWA_STAFF_SESSION_RUNTIME_EPOCH": "SYNTHETIC-media-derivative-native-runtime-v1",
}


@override_settings(**FEATURES)
class MediaDerivativeBrowserTests(DerivativeFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        self.session_policy = native.SessionPolicy(self.directory)
        self.enterContext(override_settings(FATWA_STAFF_SESSION_AUTHORITY=self.session_policy))
        self.picture = picture()
        case = Case.objects.get(pk=self.receipt["case_id"])
        self.image = attachments.upload(
            token=self.receipt["token"],
            raw=self.picture,
            filename="synthetic-original-image.png",
            media_type="image/png",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )

    def sync(self, call):
        def work():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SET lock_timeout = '5s'")
                return call()
            finally:
                connections.close_all()

        # SQL and the actual processor have their own finite bounds. This helper
        # only keeps synchronous ORM work outside Playwright's event-loop thread.
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(work).result(timeout=45)

    def originals(self):
        result = {}
        for model in (
            Case,
            CaseEvidence,
            CaseEvent,
            CaseAttachment,
            AnswerRevision,
            AnswerPart,
            CaseDecision,
        ):
            values = list(model.objects.order_by("pk").values())

            def encode(value):
                return bytes(value).hex() if isinstance(value, (bytes, memoryview)) else str(value)

            result[model._meta.db_table] = sha256(
                json.dumps(values, sort_keys=True, default=encode).encode()
            ).hexdigest()
        return result

    def stage(self, name):
        with (OUT / "progress.jsonl").open("a") as stream:
            stream.write(json.dumps({"stage": name, "monotonic": time.monotonic()}) + "\n")

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.press("Enter")
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name, *, html=True):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            filename = f"{name}-{width}.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            self.proof["screenshots"].append(filename)
            if html:
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                actual_width = page.evaluate("document.documentElement.scrollWidth")
                if actual_width > width:
                    overflow = page.evaluate("""() => Array.from(document.querySelectorAll('body *'))
                        .map(el => ({tag: el.tagName, left: el.getBoundingClientRect().left,
                            right: el.getBoundingClientRect().right,
                            clientWidth: el.clientWidth, scrollWidth: el.scrollWidth}))
                        .filter(el => el.left < 0 || el.right > innerWidth
                            || el.scrollWidth > el.clientWidth + 1).slice(0, 30)""")
                    (OUT / f"{name}-{width}-overflow.json").write_text(json.dumps(overflow))
                self.assertLessEqual(actual_width, width)

    def enqueue(self, page, identifier, task):
        form = page.locator(
            f'form[data-derivative-source="ATTACHMENT:{identifier}"][data-derivative-task="{task}"]'
        )
        self.assertEqual(form.count(), 1)
        self.submit(page, form.get_by_role("button"))
        job = page.locator('section[data-job-state="QUEUED"]')
        self.assertEqual(job.count(), 1)
        return job.get_attribute("data-job-id")

    def worker(self, identifier):
        self.stage("worker-start-" + identifier)

        def work():
            self.assertFalse(connection.in_atomic_block)
            result = io.StringIO()
            with override_settings(FATWA_MEDIA_DERIVATIVES_WORKER_DIRECTORY=self.directory):
                call_command(
                    "process_media_derivative",
                    job=identifier,
                    synthetic_fixtures_only=True,
                    stdout=result,
                )
            return json.loads(result.getvalue())["jobs"][0]

        result = self.sync(work)
        self.stage("worker-end-" + result["state"])
        return result

    def refresh(self, page):
        self.submit(page, page.get_by_role("button", name="تحديث حالة المهام", exact=True))

    def download(self, page, section, filename):
        with page.expect_download() as waiting:
            section.get_by_role("button", name="تنزيل المشتقة", exact=True).press("Enter")
        download = waiting.value
        self.assertIsNone(download.failure())
        download.save_as(str(OUT / filename))
        return (OUT / filename).read_bytes()

    def denied(self, page, url, label):
        response = page.goto(self.live_server_url + url, wait_until="domcontentloaded")
        self.assertEqual(response.status, 404)
        body = page.locator("body").inner_text()
        self.assertEqual(set(json.loads(body)), {"error"})
        self.assertNotIn("private-original", body)
        self.assertNotIn(self.receipt["public_ref"], body)
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("no-store", response.headers["cache-control"])
        for name in ("content-range", "content-disposition", "etag", "x-content-sha256"):
            self.assertNotIn(name, response.headers)
        self.proof["denials"].append(label)
        self.capture(page, label, html=False)

    def test_native_queue_retry_original_playback_download_cancel_and_revocation(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected media proof requires FATWA_BROWSER_SANDBOX=1")
        self.assertEqual(settings.ROOT_URLCONF, "config.campaign_urls")
        self.assertEqual(settings.MIDDLEWARE, campaign_review.MIDDLEWARE)
        self.assertLess(
            settings.MIDDLEWARE.index("apps.staff_sessions.middleware.SessionContext"),
            settings.MIDDLEWARE.index("apps.media_derivatives.policy.DerivativeResponses"),
        )
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "progress.jsonl").write_text("")
        before = self.originals()
        self.proof = {
            "status": "ERROR",
            "sandbox": True,
            "protected_browser": True,
            "widths": [320, 1280],
            "screenshots": [],
            "traces": [],
            "external_requests": [],
            "page_errors": [],
            "denials": [],
            "scanner_mode": "SYNTHETIC",
            "actual_asr_provider": "UNAVAILABLE_NO_PROVIDER",
        }
        responses = []
        origin = self.live_server_url

        def local(route):
            parsed = urlsplit(route.request.url)
            if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                self.proof["external_requests"].append("blocked")
                route.abort()
            else:
                route.continue_()

        context = browser = None
        with (OUT / "stacks.log").open("w") as diagnostic:
            faulthandler.dump_traceback_later(90, repeat=True, file=diagnostic)
            try:
                with sync_playwright() as p:
                    self.stage("protected-browser-start")
                    browser = p.chromium.launch(
                        executable_path=os.environ.get(
                            "FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"
                        ),
                        chromium_sandbox=True,
                        args=["--disable-dev-shm-usage"],
                    )
                    try:
                        context = browser.new_context(
                            viewport={"width": 320, "height": 900}, accept_downloads=True
                        )
                        context.route("**/*", local)
                        context.on(
                            "response",
                            lambda response: responses.append((response.url, response.status)),
                        )
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: self.proof["page_errors"].append(type(error).__name__),
                        )
                        page.set_default_timeout(20000)
                        self.assertEqual(page.goto(origin + "/casework/staff/login/").status, 200)
                        page.locator("#credential").fill(
                            "synthetic-editor-credential-32-characters"
                        )
                        self.submit(
                            page, page.get_by_role("button", name="دخول المكتب", exact=True)
                        )
                        self.assertEqual(self.sync(lambda: Session.objects.count()), 1)
                        with page.expect_navigation(wait_until="domcontentloaded"):
                            page.get_by_role("link", name="مهام الوسائط", exact=True).click()
                        self.assertEqual(urlsplit(page.url).path, BASE)
                        self.submit(
                            page,
                            page.get_by_role(
                                "button", name="فتح مهام " + self.receipt["public_ref"], exact=True
                            ),
                        )

                        self.stage("native-queue-unavailable")
                        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
                            audio_id = self.enqueue(page, self.attachment["id"], "AUDIO_PLAYBACK")
                            self.capture(page, "queued")
                            self.assertEqual(self.worker(audio_id)["state"], "UNAVAILABLE")
                            self.refresh(page)
                            article = page.locator(f'section[data-job-id="{audio_id}"]')
                            self.assertEqual(article.get_attribute("data-job-state"), "UNAVAILABLE")
                            link = article.get_by_role("link", name="فتح الأصل المحفوظ", exact=True)
                            source_url = link.get_attribute("href")
                            with page.expect_popup() as opened:
                                link.click()
                            original = opened.value
                            original.wait_for_load_state("domcontentloaded")
                            self.assertEqual(
                                urlsplit(original.url).path,
                                "/casework/staff/attachments/" + self.attachment["id"] + "/",
                            )
                            # This supplemental exact read follows a real native
                            # original-link navigation; it does not replace it.
                            source = context.request.get(origin + source_url, timeout=20000)
                            self.assertEqual(source.status, 200)
                            self.assertEqual(source.body(), self.raw)
                            self.assertTrue(
                                any(
                                    url == origin + source_url and status in {200, 206}
                                    for url, status in responses
                                )
                            )
                            original.close()
                            self.capture(page, "unavailable-original-preserved")

                        self.stage("native-retry-real-ffmpeg")
                        self.submit(
                            page,
                            article.get_by_role(
                                "button", name="إعادة المحاولة بإذن حالي", exact=True
                            ),
                        )
                        self.assertEqual(self.worker(audio_id)["state"], "READY")
                        self.refresh(page)
                        article = page.locator(f'section[data-job-id="{audio_id}"]')
                        self.assertEqual(article.get_attribute("data-job-state"), "READY")
                        player = article.locator("audio[controls]")
                        self.assertTrue(player.is_visible())
                        self.assertIsNone(player.get_attribute("autoplay"))
                        player.press("Space")
                        selector = f'section[data-job-id="{audio_id}"] audio'
                        page.wait_for_function(
                            "selector => { const a=document.querySelector(selector); return a && a.readyState>=1 && a.duration>0 && !a.error && a.played.length>0; }",
                            arg=selector,
                        )
                        media = player.evaluate(
                            "a => ({duration:a.duration,paused:a.paused,time:a.currentTime})"
                        )
                        if not media["paused"]:
                            player.press("Space")
                        output_url = player.get_attribute("src")
                        self.assertTrue(
                            any(
                                url == origin + output_url and status in {200, 206}
                                for url, status in responses
                            )
                        )
                        downloaded = self.download(page, article, "playback.wav")
                        self.assertEqual(downloaded, self.raw)
                        self.capture(page, "ready-native-playback-download")

                        self.stage("native-thumbnail")
                        image_id = self.enqueue(page, self.image["id"], "THUMBNAIL")
                        self.assertEqual(self.worker(image_id)["state"], "READY")
                        self.refresh(page)
                        thumbnail = page.locator(f'section[data-job-id="{image_id}"]')
                        image_selector = f'section[data-job-id="{image_id}"] img'
                        page.wait_for_function(
                            "selector => { const i=document.querySelector(selector); return i && i.complete && i.naturalWidth===320 && i.naturalHeight===160; }",
                            arg=image_selector,
                        )
                        self.assertTrue(thumbnail.locator("img").is_visible())
                        png = self.download(page, thumbnail, "thumbnail.png")
                        self.assertNotEqual(png, self.picture)
                        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
                        self.capture(page, "ready-native-thumbnail")

                        self.stage("native-cancel")
                        cancelled = self.enqueue(page, self.attachment["id"], "AUDIO_PLAYBACK")
                        pending = page.locator(f'section[data-job-id="{cancelled}"]')
                        self.submit(
                            page, pending.get_by_role("button", name="إلغاء المهمة", exact=True)
                        )
                        self.assertEqual(pending.get_attribute("data-job-state"), "CANCELLED")
                        with patch.object(
                            execution.FFmpegProcessor,
                            "run",
                            side_effect=AssertionError("cancelled processor reached"),
                        ):
                            self.assertEqual(self.worker(cancelled)["state"], "NOT_EXECUTED")
                        self.capture(page, "cancelled-original-preserved")
                        self.assertEqual(
                            page.locator(
                                '[data-transcription-state="UNAVAILABLE_NO_PROVIDER"]'
                            ).count(),
                            1,
                        )

                        self.stage("native-current-source-and-scan-denials")
                        reader = context.new_page()
                        self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
                        self.denied(reader, output_url, "source-read-revoked")
                        self.rights.denied.clear()
                        current = self.scanner.current
                        self.scanner.current = replace(
                            current, signature_version="SYNTHETIC-native-media-revoked"
                        )
                        self.denied(reader, output_url, "source-scan-revoked")
                        self.scanner.current = current
                        partial = context.request.get(
                            origin + output_url, headers={"Range": "bytes=8-23"}, timeout=20000
                        )
                        self.assertEqual((partial.status, partial.body()), (206, self.raw[8:24]))
                        head = context.request.head(origin + output_url, timeout=20000)
                        self.assertEqual((head.status, head.body()), (200, b""))
                        self.assertEqual(int(head.headers["content-length"]), len(self.raw))
                        self.assertEqual(self.sync(self.originals), before)
                        saved = self.sync(
                            lambda: list(
                                DerivedOutput.objects.order_by("created_at").values(
                                    "sha256", "engine", "source_digest"
                                )
                            )
                        )
                        self.assertEqual(len(saved), 2)
                        self.assertTrue(
                            all(row["engine"]["mode"] == "LOCAL_FFMPEG" for row in saved)
                        )
                        self.assertTrue(
                            self.sync(
                                lambda: all(
                                    DerivativeJob.objects.values_list(
                                        "origin_session_id", flat=True
                                    )
                                )
                            )
                        )
                        self.assertEqual(self.proof["external_requests"], [])
                        self.assertEqual(self.proof["page_errors"], [])
                        self.proof.update(
                            status="PASS",
                            native_actions=True,
                            actual_ffmpeg=True,
                            actual_native_audio_playback=media,
                            original_bytes_preserved=True,
                            canonical_histories_unchanged=True,
                            unavailable_original_opened=True,
                            explicit_retry=True,
                            explicit_cancellation=True,
                            source_bound_outputs=True,
                            positive_reads_after_denial=True,
                            actual_session_origins=True,
                            original_audio_sha256=sha256(self.raw).hexdigest(),
                            original_image_sha256=sha256(self.picture).hexdigest(),
                            downloaded_audio_sha256=sha256(downloaded).hexdigest(),
                            downloaded_thumbnail_sha256=sha256(png).hexdigest(),
                            output_provenance=saved,
                        )
                        self.stage("native-proof-complete")
                    finally:
                        if context:
                            context.tracing.stop(path=str(OUT / "trace-staff.zip"))
                            self.proof["traces"].append("trace-staff.zip")
                            context.close()
                        if browser:
                            browser.close()
            finally:
                faulthandler.cancel_dump_traceback_later()
                (OUT / "result.json").write_text(
                    json.dumps(self.proof, ensure_ascii=False, indent=2) + "\n"
                )
