"""Protected native source upload, independent rights, real video and withdrawal."""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case
from apps.private_media.filesystem import BACKEND, FileSystemStorage

from .models import LibraryBlob, LibraryDecision, LibraryVersion
from .test_support import FEATURES, LibraryFixture, payload, video

OUT = Path(".local/qa/functional-continuation/library-browser")
CREDENTIALS = {
    "editor": "synthetic-editor-credential-32-characters",
    "other": "synthetic-reviewer-credential-32-characters",
    "publisher": "synthetic-publisher-credential-32-characters",
}


@override_settings(**FEATURES)
class LibraryBrowserTests(LibraryFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        # Setup creates only the synthetic case, trusted identities and private
        # storage. Every library version and decision comes from a native form.
        folder = tempfile.TemporaryDirectory(prefix="library-browser-originals-")
        self.addCleanup(folder.cleanup)
        self.storage = FileSystemStorage(
            Path(folder.name) / "private", synthetic_fixtures_only=True
        )
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as workers:
            return workers.submit(work).result(timeout=30)

    def form(self, page, action, *, host=None):
        selected = (host or page).locator(f'form:visible:has([name="action"][value="{action}"])')
        self.assertEqual(selected.count(), 1, "ambiguous native library action: " + action)
        return selected

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.press("Enter")
        self.assertIsNotNone(navigation.value)
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def send(self, page, form):
        self.submit(page, form.locator('button:visible:not([type="button"])'))

    def login(self, page, subject):
        response = page.goto(self.live_server_url + "/casework/staff/login/")
        self.assertEqual(response.status, 200)
        page.locator("#credential").fill(CREDENTIALS[subject])
        self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))

    def open_library(self, page, *, selected=False):
        response = page.goto(self.live_server_url + "/casework/staff/")
        self.assertEqual(response.status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))
        self.send(page, self.form(page, "rl_open"))
        if selected:
            self.submit(page, page.get_by_role("button", name="فتح المادة ونسخها", exact=True))

    def decision(self, page, action):
        form = page.locator(f'form.library-decision[data-command="{action}"]')
        self.assertEqual(form.count(), 1)
        form.locator('[name="note"]').fill("قرار بشري اصطناعي للنسخة والحقوق: " + action)
        form.locator('[name="confirmed"]').check()
        if action == "APPROVE":
            for usage in ("READ", "DOWNLOAD", "PUBLIC_METADATA", "PUBLIC_CONTENT"):
                form.locator(f'[name="uses"][value="{usage}"]').check()
            form.locator('[name="minutes"]').fill("30")
        elif action == "RELEASE":
            form.locator('[name="minutes"]').fill("15")
        self.send(page, form)

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)
            proof["screenshots"].append(f"{label}-{width}.png")

    def playable(self, page):
        self.assertEqual(page.locator("video[controls]").count(), 1)
        page.wait_for_function(
            """() => {
                const video = document.querySelector('video[controls]');
                return video && video.readyState >= 1 && Number.isFinite(video.duration)
                    && video.duration > 0 && video.videoWidth > 0 && !video.error;
            }"""
        )

    def download(self, page, label):
        link = page.get_by_role("link", name="تنزيل الملف المصرح به", exact=True)
        self.assertEqual(link.count(), 1)
        with page.expect_download() as waiting:
            link.click()
        downloaded = waiting.value
        self.assertIsNone(downloaded.failure())
        destination = OUT / (label + ".webm")
        downloaded.save_as(str(destination))
        self.assertEqual(destination.read_bytes(), video())

    def test_native_external_video_rights_versions_and_public_revocation(self):
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
            "storage_backend": BACKEND,
            "file_sha256": sha256(video()).hexdigest(),
            "observed_statuses": {},
        }
        origin = self.live_server_url
        contexts = []
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

                    def new_page(label):
                        context = browser.new_context(
                            viewport={"width": 320, "height": 780}, accept_downloads=True
                        )
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    editor = new_page("editor")
                    self.login(editor, "editor")
                    self.open_library(editor)
                    form = editor.locator("#library-save")
                    form.locator('[name="namespace"]').fill("synthetic-browser-library")
                    form.locator('[name="external_id"]').fill("native-video")
                    values = payload("VIDEO", title="تسجيل مرئي اصطناعي — نسخة أولى")
                    for key, value in values.items():
                        if key in {"synthetic", "kind", "language"}:
                            continue
                        form.locator(f'[name="{key}"]').fill(value)
                    form.locator('[name="kind"]').select_option("VIDEO")
                    form.locator('[name="language"]').select_option("ar")
                    form.locator('[name="source_file"]').set_input_files(
                        {"name": "native-video.webm", "mimeType": "video/webm", "buffer": video()}
                    )
                    self.send(editor, form)
                    first_id = editor.locator("#library-selected").get_attribute(
                        "data-library-version"
                    )
                    self.assertEqual(editor.locator("video").count(), 0)
                    self.assertIn("لم تُتح قراءة", editor.locator("main").inner_text())
                    probe = editor.context.new_page()
                    response = probe.goto(origin + f"/casework/staff/library/{first_id}/file/")
                    self.assertEqual(response.status, 404)
                    proof["observed_statuses"]["private_before_approval"] = response.status
                    probe.close()

                    reviewer = new_page("reviewer")
                    self.login(reviewer, "other")
                    self.open_library(reviewer, selected=True)
                    self.decision(reviewer, "REVIEW")
                    publisher = new_page("publisher")
                    self.login(publisher, "publisher")
                    self.open_library(publisher, selected=True)
                    with publisher.expect_response(
                        lambda response: (
                            response.url == origin + f"/casework/staff/library/{first_id}/file/"
                        )
                    ) as media_response:
                        self.decision(publisher, "APPROVE")
                    self.assertEqual(media_response.value.status, 200)
                    self.playable(publisher)
                    self.download(publisher, "private-video")
                    self.capture(publisher, "private-video", proof)
                    proof["observed_statuses"]["private_after_approval"] = (
                        media_response.value.status
                    )
                    self.decision(publisher, "RELEASE")

                    anonymous = new_page("public")
                    response = anonymous.goto(origin + "/library-preview/materials/")
                    self.assertEqual(response.status, 200)
                    link = anonymous.get_by_role("link", name=values["title"], exact=True)
                    self.assertEqual(link.count(), 1)
                    public_path = link.get_attribute("href")
                    response = anonymous.goto(origin + public_path)
                    self.assertEqual(response.status, 200)
                    proof["observed_statuses"]["public_released"] = response.status
                    self.playable(anonymous)
                    self.download(anonymous, "public-video")
                    text = anonymous.locator("main").inner_text()
                    self.assertNotIn(self.receipt["public_ref"], text)
                    self.assertNotIn(values["provenance"], text)
                    self.assertNotIn(values["rights_basis"], text)
                    self.capture(anonymous, "public-video", proof)

                    self.open_library(editor, selected=True)
                    self.send(editor, self.form(editor, "rl_edit"))
                    form = editor.locator("#library-save")
                    self.assertEqual(form.locator('[name="source_file"]').input_value(), "")
                    form.locator('[name="title"]').fill("نسخة ثانية بشرية تنتظر مراجعة مستقلة")
                    form.locator('[name="edition_label"]').fill("نسخة ثانية")
                    self.send(editor, form)
                    second_id = editor.locator("#library-selected").get_attribute(
                        "data-library-version"
                    )
                    self.assertNotEqual(first_id, second_id)
                    self.assertEqual(editor.locator("video").count(), 0)
                    self.assertIn("لم تُتح قراءة", editor.locator("main").inner_text())
                    probe = editor.context.new_page()
                    response = probe.goto(origin + f"/casework/staff/library/{second_id}/file/")
                    self.assertEqual(response.status, 404)
                    proof["observed_statuses"]["new_edition_without_rights"] = response.status
                    probe.close()
                    self.capture(editor, "new-edition-unapproved", proof)
                    response = anonymous.goto(origin + public_path)
                    self.assertEqual(response.status, 200)
                    proof["observed_statuses"]["old_public_version_after_new_draft"] = (
                        response.status
                    )
                    self.playable(anonymous)
                    self.assertIn(values["title"], anonymous.locator("h1").inner_text())

                    # Publisher still has the explicit first-edition form. Its
                    # revision/action pins remain current and never float to v2.
                    self.decision(publisher, "REVOKE")
                    response = anonymous.goto(origin + public_path)
                    self.assertEqual(response.status, 404)
                    proof["observed_statuses"]["public_after_revoke"] = response.status
                    self.assertEqual(anonymous.locator("video").count(), 0)
                    self.assertNotIn(values["title"], anonymous.locator("body").inner_text())

                    def observed():
                        case = Case.objects.get(pk=self.receipt["case_id"])
                        blob = LibraryBlob.objects.get()
                        return (
                            case.revision,
                            case.evidence_version,
                            case.answers.count(),
                            case.decisions.count(),
                            case.events.count(),
                            LibraryVersion.objects.count(),
                            LibraryDecision.objects.count(),
                            blob.storage_backend,
                            blob.original,
                            blob.sha256,
                        )

                    self.assertEqual(
                        self.sync(observed),
                        (1, 1, 0, 0, 1, 2, 4, BACKEND, None, proof["file_sha256"]),
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
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
