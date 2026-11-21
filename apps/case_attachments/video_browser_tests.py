"""Actual requester video upload, playback and current private-file boundaries."""

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.private_media.filesystem import FileSystemStorage
from tests.casework.test_http import Directory

from .models import CaseAttachment
from .tests import new_case, staff_common
from .video_fixtures import video
from .video_tests import FEATURES

OUT = Path(".local/qa/functional-continuation/requester-video-browser")


@override_settings(**FEATURES)
class RequesterVideoBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        self.receipt, self.other = new_case(), new_case()
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        self.folder = tempfile.TemporaryDirectory(prefix="requester-video-browser-")
        self.addCleanup(self.folder.cleanup)
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(
                Path(self.folder.name) / "originals", synthetic_fixtures_only=True
            ),
        )
        configured.enable()
        self.addCleanup(configured.disable)
        draft = cases.save_answer(**staff_common(self.receipt), text="جواب سابق لوصول مرفق السؤال",
                                  expected_revision=1, expected_evidence_version=1)
        cases.record_decision(**staff_common(self.receipt), answer_id=draft["answers"][0]["id"],
                              action="APPROVE", expected_revision=2, expected_evidence_version=1)

    def sync(self, callback):
        def run():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=40)

    def submit(self, page, button):
        with page.expect_navigation(wait_until="domcontentloaded") as waiting:
            button.focus()
            button.press("Enter")
        self.assertEqual(waiting.value.status, 200)
        self.assertIn("no-store", waiting.value.headers.get("cache-control", ""))

    def unlock(self, page, receipt):
        self.assertEqual(page.goto(self.live_server_url + "/casework/status/").status, 200)
        page.locator("#workspace-token").fill(receipt["token"])
        self.submit(page, page.get_by_role("button", name="فتح المتابعة الخاصة", exact=True))
        self.submit(page, page.get_by_role("button", name="مرفقات سؤالي", exact=True))

    def capture(self, page, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
            proof["screenshots"].append(f"{name}-{width}.png")

    def video_state(self, page, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = page.locator("video[controls]").evaluate(
                "video => ({ready:video.readyState,time:video.currentTime,duration:video.duration,"
                "width:video.videoWidth,error:video.error?.code || null,paused:video.paused})"
            )
            if predicate(state):
                return state
            page.wait_for_timeout(50)
        self.fail("Native video did not reach expected playback state: " + repr(state))

    def test_native_requester_upload_playback_original_download_and_revocation(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {"status": "ERROR", "sandbox": True, "widths": [320, 1280],
                 "screenshots": [], "traces": [], "page_errors": [], "external_requests": []}
        contexts = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                    chromium_sandbox=True, args=["--disable-dev-shm-usage"],
                )
                try:
                    for role in ("requester", "staff", "foreign"):
                        context = browser.new_context(viewport={"width": 320, "height": 900}, accept_downloads=True)
                        context.tracing.start(screenshots=True, snapshots=True)
                        contexts.append((role, context))
                        def route(request):
                            parsed = urlsplit(request.request.url)
                            if parsed.scheme == "http" and parsed.netloc == urlsplit(self.live_server_url).netloc:
                                request.continue_()
                            else:
                                proof["external_requests"].append(request.request.url)
                                request.abort()
                        context.route("**/*", route)
                    page, staff, foreign = [context.new_page() for _, context in contexts]
                    for opened in (page, staff, foreign):
                        opened.on("pageerror", lambda error: proof["page_errors"].append(str(error)))
                    self.unlock(page, self.receipt)
                    page.locator('[name="attachment"]').set_input_files(
                        {"name": "requester-video.webm", "mimeType": "video/webm", "buffer": video()}
                    )
                    page.locator('[name="synthetic_only"]').check()
                    self.submit(page, page.get_by_role("button", name="حفظ الأصل وإضافة الوقائع", exact=True))
                    observed = self.sync(lambda: list(CaseAttachment.objects.values("id", "sha256", "storage_backend", "kind")))
                    self.assertEqual(len(observed), 1)
                    row = observed[0]
                    self.assertEqual((row["kind"], row["storage_backend"]), ("video", "private-filesystem-v1"))
                    self.assertEqual(row["sha256"], sha256(video()).hexdigest())
                    proof["original_sha256"] = row["sha256"]
                    self.submit(page, page.get_by_role("button", name="معاينة requester-video.webm", exact=True))
                    self.video_state(page, lambda state: state["ready"] >= 1 and state["width"] > 0 and state["duration"] > 0 and state["error"] is None)
                    # The native focused player receives a real user gesture.
                    page.locator("video[controls]").press("Space")
                    advanced = self.video_state(page, lambda state: state["time"] >= 0.15 and state["error"] is None)
                    proof["native_playback_seconds"] = advanced["time"]
                    self.capture(page, "requester-video", proof)
                    with page.expect_download() as waiting:
                        page.get_by_role("button", name="تنزيل الأصل requester-video.webm", exact=True).click()
                    downloaded = waiting.value
                    self.assertIsNone(downloaded.failure())
                    saved = OUT / "requester-original.webm"
                    downloaded.save_as(str(saved))
                    self.assertEqual(saved.read_bytes(), video())
                    proof["download"] = {"file": saved.name, "sha256": sha256(saved.read_bytes()).hexdigest(), "size": saved.stat().st_size}
                    case_state = self.sync(lambda: Case.objects.values("revision", "evidence_version", "approved_answer_id", "stage").get(pk=self.receipt["case_id"]))
                    self.assertEqual(case_state, {"revision": 4, "evidence_version": 2, "approved_answer_id": None, "stage": "UNDER_REVIEW"})
                    proof["new_facts_invalidated_approval"] = True
                    self.assertEqual(staff.goto(self.live_server_url + "/casework/staff/login/").status, 200)
                    staff.locator("#credential").fill(self.directory.credential)
                    self.submit(staff, staff.get_by_role("button", name="دخول المكتب", exact=True))
                    self.submit(staff, staff.get_by_role("button", name=self.receipt["public_ref"], exact=True))
                    self.submit(staff, staff.get_by_role("button", name="مرفقات القضية", exact=True))
                    self.submit(staff, staff.get_by_role("button", name="معاينة requester-video.webm", exact=True))
                    self.video_state(staff, lambda state: state["ready"] >= 1 and state["width"] > 0 and state["error"] is None)
                    self.capture(staff, "staff-video", proof)
                    self.unlock(foreign, self.other)
                    requester_url = self.live_server_url + "/casework/status/attachments/" + str(row["id"]) + "/"
                    staff_url = requester_url.replace("/status/", "/staff/")
                    self.assertEqual(foreign.goto(requester_url).status, 404)
                    self.directory.current = replace(self.directory.current, active=False)
                    self.assertIn(staff.goto(staff_url).status, (403, 404))
                    self.sync(lambda: cases.revoke_access(**staff_common(self.receipt), requester_id=Case.objects.get(pk=self.receipt["case_id"]).requester_id))
                    self.assertEqual(page.goto(requester_url).status, 404)
                    proof["foreign_case_denied"] = proof["revoked_staff_denied"] = proof["revoked_requester_denied"] = True
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof["status"] = "PASS"
                finally:
                    for role, context in contexts:
                        name = role + "-trace.zip"
                        context.tracing.stop(path=str(OUT / name))
                        proof["traces"].append(name)
                        context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
