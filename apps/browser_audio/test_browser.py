"""Synthetic microphone in real Chromium; native forms and existing private services."""

import base64
import io
import math
import os
import struct
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.guard import ROUTES
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import validate
from tests.casework.test_http import WEB_SETTINGS, Directory

from .assets import ASSET_ROUTES

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.browser_audio.test_support",
    "MIDDLEWARE": [
        "apps.browser_audio.test_support.CaptureComposition",
        *WEB_SETTINGS["MIDDLEWARE"],
    ],
    "FATWA_BROWSER_AUDIO_ENABLED": True,
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
}

# Observers retain test handles only. Native getUserMedia and AudioContext still run.
OBSERVE = """() => {
 window.probe = {streams: [], contexts: [], calls: 0, urls: new Set()};
 const native = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
 navigator.mediaDevices.getUserMedia = async (...args) => {
   probe.calls++; const stream = await native(...args); probe.streams.push(stream); return stream;
 };
 const Audio = window.AudioContext;
 window.AudioContext = class extends Audio { constructor(...args) {super(...args); probe.contexts.push(this);} };
 const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
 URL.createObjectURL = value => {const url = create(value); probe.urls.add(url); return url;};
 URL.revokeObjectURL = url => {probe.urls.delete(url); return revoke(url);};
}"""


def recorder(page):
    """Exercise the upload/editor under test, independently of the reply recorder."""
    return page.locator(
        'form:has([name="action"][value="attachment_upload"]) [data-browser-audio], '
        'form:has([name="action"][value="answer_media_save"]) [data-browser-audio]'
    )


@override_settings(**FEATURES)
class BrowserAudioTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        self.receipt = cases.intake_case(
            original_question="سؤال صوتي اصطناعي فقط",
            source_event_id="v13-audio",
            requester_id="v13-requester",
            idempotency_key="v13-audio",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.temp = TemporaryDirectory(prefix="v13-audio-private-")
        self.addCleanup(self.temp.cleanup)
        self.storage = FileSystemStorage(self.temp.name, synthetic_fixtures_only=True)
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        routes = patch.dict(ROUTES, ASSET_ROUTES)
        routes.start()
        self.addCleanup(routes.stop)

    def sync(self, callback):
        def invoke():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(invoke).result(timeout=30)

    def browser(self, playwright):
        self.external = []
        config = TemporaryDirectory(prefix="v13-browser-config-")
        self.addCleanup(config.cleanup)
        microphone = Path(config.name) / "synthetic-microphone.wav"
        with wave.open(str(microphone), "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(48000)
            sound.writeframes(
                b"".join(
                    struct.pack("<h", int(10000 * math.sin(i * 2 * math.pi * 440 / 48000)))
                    for i in range(96000)
                )
            )
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
            chromium_sandbox=os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0",
            args=[
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={microphone}",
            ],
            env={**os.environ, "XDG_CONFIG_HOME": config.name},
        )
        return browser

    def context(self, browser):
        context = browser.new_context(viewport={"width": 320, "height": 900})
        context.grant_permissions(["microphone"], origin=self.live_server_url)
        context.add_init_script(f"({OBSERVE})();")

        def route(request):
            if request.request.url.startswith(self.live_server_url + "/"):
                request.continue_()
            else:
                self.external.append(request.request.url)
                request.abort()

        context.route("**/*", route)
        return context

    def click(self, page, button, code=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.click()
        self.assertEqual(navigation.value.status, code, page.content()[:200])

    def requester(self, browser):
        page = self.context(browser).new_page()
        page.goto(self.live_server_url + "/casework/status/")
        page.locator("#portal-token").fill(self.receipt["token"])
        self.click(page, page.get_by_role("button", name="فتح قضيتي", exact=True))
        page.wait_for_function(
            "() => document.querySelector('[data-browser-audio]')?.dataset.audioState === 'idle'"
        )
        return page

    def action(self, page, action):
        # Navigation only: preserve real CSRF cookie/token and original authenticated route.
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            page.evaluate(
                """values => {
              const form = document.createElement('form'); form.method = 'post'; form.action = '/casework/staff/';
              values.csrfmiddlewaretoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
              for (const [name,value] of Object.entries(values)) {
                const input = document.createElement('input'); input.name = name; input.value = value; form.append(input);
              } document.body.append(form); form.submit();
            }""",
                {"action": action, "case_ref": self.receipt["public_ref"]},
            )
        self.assertEqual(navigation.value.status, 200)

    def record(self, page, *, automatic=False):
        page.wait_for_function(
            "() => document.querySelector('[data-browser-audio]')?.dataset.audioState === 'idle'"
        )
        self.assertEqual(page.evaluate("probe.calls"), 0)
        recorder(page).locator("[data-audio-start]").click()
        page.wait_for_function(
            "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'recording'"
        )
        if not automatic:
            page.wait_for_function(
                "() => +document.querySelector('[data-browser-audio]').dataset.audioFrames >= 1600"
            )
            recorder(page).locator("[data-audio-stop]").click()
        page.wait_for_function(
            "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'preview'"
        )
        self.released(page)
        recorder(page).locator("[data-audio-accept]").click()
        encoded = page.locator('input[type="file"]').first.evaluate("""async input => {
            const bytes = new Uint8Array(await input.files[0].arrayBuffer());
            let out = ''; for (const b of bytes) out += String.fromCharCode(b); return btoa(out);
        }""")
        raw = base64.b64decode(encoded)
        parsed = validate(raw, "capture.wav", "audio/wav")
        self.assertLessEqual(len(raw), 160044)
        self.assertEqual(parsed.metadata["sample_rate"], 8000)
        self.assertEqual(parsed.metadata["channels"], 1)
        with wave.open(io.BytesIO(raw)) as audio:
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertGreater(audio.getnframes(), 0)
            self.assertNotEqual(set(audio.readframes(audio.getnframes())), {0})
        return raw, parsed

    def released(self, page):
        page.wait_for_function(
            "() => probe.contexts.every(c=>c.state==='closed') && probe.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'))"
        )

    def approve_release(self):
        current = cases.read_case(**self.common)
        cases.record_decision(
            **self.common,
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        current = answers.staff_snapshot(**self.common)
        answers.release_private(
            **self.common,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=current["latest_package"]["sha256"],
            confirmed=True,
        )

    def test_capture_native_private_attachment_and_answer_revision(self):
        from playwright.sync_api import sync_playwright

        current = cases.read_case(**self.common)
        answers.save_multipart_answer(
            **self.common,
            text="جواب سابق اصطناعي",
            files=[audio_fixture()],
            expected_revision=current["revision"],
            expected_evidence_version=1,
        )
        self.approve_release()
        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            try:
                page = self.requester(browser)
                raw, parsed = self.record(page)
                form = page.locator('form:has([name="action"][value="attachment_upload"])')
                form.locator('[name="synthetic_only"]').check()
                self.click(page, form.locator('button:not([type="button"])'))
                row = self.sync(lambda: CaseAttachment.objects.get())
                self.assertIsNone(row.original)
                self.assertEqual(row.sha256, sha256(raw).hexdigest())
                self.assertEqual(row.validation_metadata, parsed.metadata)
                self.assertEqual(
                    self.sync(
                        lambda: attachments.requester_read(
                            token=self.receipt["token"],
                            attachment_id=str(row.pk),
                            synthetic_fixtures_only=True,
                        )
                    )["raw"],
                    raw,
                )
                current = self.sync(lambda: cases.read_case(**self.common))
                self.assertEqual(current["evidence_version"], 2)
                self.assertIsNone(current["approved_answer_id"])
                staff = self.context(browser).new_page()
                staff.goto(self.live_server_url + "/casework/staff/login/")
                staff.locator("#credential").fill(self.directory.credential)
                self.click(staff, staff.get_by_role("button", name="دخول المكتب", exact=True))
                self.action(staff, "answer_media")
                answer_raw, _ = self.record(staff)
                form = staff.locator('form:has([name="action"][value="answer_media_save"])')
                form.locator('[name="text"]').fill("جواب صوتي بشري اصطناعي")
                form.locator('[name="synthetic_only"]').check()
                self.click(staff, form.locator('button:not([type="button"])'))
                part = self.sync(lambda: AnswerPart.objects.filter(filename="capture.wav").get())
                self.assertIsNone(part.original)
                self.assertEqual(self.sync(lambda: answers.raw_for_part(part)), answer_raw)
                self.assertEqual(part.sha256, sha256(answer_raw).hexdigest())
                self.assertEqual(self.sync(lambda: Case.objects.get().evidence_version), 2)
                self.sync(self.approve_release)
                self.assertEqual(
                    self.sync(
                        lambda: answers.requester_read(
                            token=self.receipt["token"],
                            part_id=str(part.pk),
                            synthetic_fixtures_only=True,
                        )
                    )["raw"],
                    answer_raw,
                )
                # Another browser recording creates a new immutable revision and closes old availability.
                self.action(staff, "answer_media")
                self.record(staff)
                form = staff.locator('form:has([name="action"][value="answer_media_save"])')
                form.locator('[name="synthetic_only"]').check()
                self.click(staff, form.locator('button:not([type="button"])'))
                self.assertIsNone(self.sync(lambda: Case.objects.get().approved_answer_id))
                with self.assertRaises(cases.CaseConflict):
                    self.sync(
                        lambda: answers.requester_read(
                            token=self.receipt["token"],
                            part_id=str(part.pk),
                            synthetic_fixtures_only=True,
                        )
                    )
                self.assertEqual(self.sync(lambda: answers.raw_for_part(part)), answer_raw)
                outsider = self.context(browser).new_page()
                self.assertEqual(
                    outsider.goto(
                        self.live_server_url + f"/casework/status/attachments/{row.pk}/"
                    ).status,
                    404,
                )
                self.directory.current = replace(self.directory.current, role="ORGANIZER")
                self.assertEqual(
                    staff.goto(
                        self.live_server_url + f"/casework/staff/answer-media/{part.pk}/"
                    ).status,
                    404,
                )
                self.assertEqual(self.external, [])
            finally:
                browser.close()

    def test_permission_denial_cancel_late_grant_limits_and_cleanup(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            try:
                page = self.requester(browser)
                self.assertEqual(page.evaluate("probe.calls"), 0)
                session = page.context.new_cdp_session(page)
                context_id = session.send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
                session.send(
                    "Browser.setPermission",
                    {
                        "permission": {"name": "microphone"},
                        "setting": "denied",
                        "origin": self.live_server_url,
                        "browserContextId": context_id,
                    },
                )
                recorder(page).locator("[data-audio-start]").click()
                page.wait_for_function(
                    "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'error'"
                )
                self.released(page)
                self.assertIn("لم يُمنح", recorder(page).locator("[data-audio-status]").inner_text())
                session.send(
                    "Browser.setPermission",
                    {
                        "permission": {"name": "microphone"},
                        "setting": "granted",
                        "origin": self.live_server_url,
                        "browserContextId": context_id,
                    },
                )
                # Real fake device stream, held at the permission-promise boundary until after cancellation.
                page.evaluate("""() => {const native=navigator.mediaDevices.getUserMedia;
                  navigator.mediaDevices.getUserMedia=async (...args)=>{const stream=await native(...args);await new Promise(r=>window.finishGrant=r);return stream;};} """)
                recorder(page).locator("[data-audio-start]").click()
                page.wait_for_function("() => typeof finishGrant === 'function'")
                recorder(page).locator("[data-audio-cancel]").click()
                page.evaluate("finishGrant()")
                self.released(page)
                self.assertEqual(
                    page.locator('[type="file"]').first.evaluate("e=>e.files.length"), 0
                )
                page.reload()
                raw, parsed = self.record(page, automatic=True)
                self.assertEqual(len(raw), 160044)
                self.assertEqual(parsed.metadata["duration_seconds"], 10)
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 320)
                recorder(page).locator("[data-audio-cancel]").click()
                self.assertEqual(
                    page.locator('[type="file"]').first.evaluate("e=>e.files.length"), 0
                )
                self.assertEqual(page.evaluate("probe.urls.size"), 0)
                recorder(page).locator("[data-audio-start]").click()
                page.wait_for_function(
                    "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'recording'"
                )
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
                self.released(page)
                self.assertEqual(self.sync(lambda: CaseAttachment.objects.count()), 0)
                self.assertEqual(self.external, [])
            finally:
                browser.close()

    def test_worklet_failure_capture_cancel_and_device_loss_release_resources(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            try:
                page = self.requester(browser)
                with override_settings(FATWA_BROWSER_AUDIO_ENABLED=False):
                    recorder(page).locator("[data-audio-start]").click()
                    page.wait_for_function(
                        "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'error'"
                    )
                self.released(page)
                self.assertEqual(
                    page.locator('[type="file"]').first.evaluate("e=>e.files.length"), 0
                )
                page.reload()
                page.wait_for_function(
                    "() => document.querySelector('[data-browser-audio]')?.dataset.audioState === 'idle'"
                )
                form = page.locator('form:has([name="action"][value="attachment_upload"])')
                form.locator('[type="file"]').set_input_files(
                    {
                        "name": "previous.wav",
                        "mimeType": "audio/wav",
                        "buffer": audio_fixture()["raw"],
                    }
                )
                form.locator('[name="synthetic_only"]').check()
                recorder(page).locator("[data-audio-start]").click()
                page.wait_for_function(
                    "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'recording'"
                )
                posts = []
                page.on(
                    "request",
                    lambda request: posts.append(request.url) if request.method == "POST" else None,
                )
                form.evaluate("form => form.requestSubmit()")
                self.assertIn("قبل حفظ النموذج", recorder(page).locator("[data-audio-status]").inner_text())
                self.assertEqual(posts, [])
                recorder(page).locator("[data-audio-cancel]").click()
                self.released(page)
                self.assertEqual(
                    form.locator('[type="file"]').evaluate("e=>e.files[0].name"), "previous.wav"
                )
                recorder(page).locator("[data-audio-start]").click()
                page.wait_for_function(
                    "() => document.querySelector('[data-browser-audio]').dataset.audioState === 'recording'"
                )
                page.evaluate(
                    "probe.streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event('ended'))"
                )
                self.released(page)
                self.assertEqual(
                    recorder(page).get_attribute("data-audio-state"), "error"
                )
                self.assertEqual(page.evaluate("probe.urls.size"), 0)
                self.assertEqual(self.sync(lambda: CaseAttachment.objects.count()), 0)
                self.assertEqual(self.external, [])
            finally:
                browser.close()
