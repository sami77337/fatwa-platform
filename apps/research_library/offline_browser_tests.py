"""Actual protected PWA, chosen local originals, offline reads and lease shortening."""

import base64
import io
import json
import os
import zipfile
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.casework.models import Case
from apps.library_preview.policy import PreviewPolicy

from . import browser_tests as native_browser
from .models import LibraryDecision, LibraryVersion
from .offline import ROOT
from .test_support import FEATURES, LibraryFixture, payload, video

OUT = Path(".local/qa/functional-continuation/offline-browser")
TEXT = "نص اصطناعي اختاره القارئ للحفظ\r\n  بايتات النسخة الأصلية لا تتغير  \n"


@override_settings(**{**FEATURES, "FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED": True})
class OfflineLibraryBrowserTests(LibraryFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = native_browser.LibraryBrowserTests.sync
    form = native_browser.LibraryBrowserTests.form
    submit = native_browser.LibraryBrowserTests.submit
    send = native_browser.LibraryBrowserTests.send
    login = native_browser.LibraryBrowserTests.login
    open_library = native_browser.LibraryBrowserTests.open_library
    decision = native_browser.LibraryBrowserTests.decision
    playable = native_browser.LibraryBrowserTests.playable

    def setUp(self):
        super().setUp()
        # Source authoring/review is fixture setup. Local SAVE/READ/REMOVE/SYNC
        # and the later source withdrawal all use their real visible UI.
        self.materials = {}
        for name, kind, title, raw, filename, media_type in (
            ("text", "BOOK", "نص محفوظ باختيار القارئ", TEXT.encode(), "chosen.txt", "text/plain"),
            ("video", "VIDEO", "فيديو محفوظ باختيار القارئ", video(), "chosen.webm", "video/webm"),
            (
                "uncached",
                "DOCUMENT",
                "مادة لم يخترها القارئ",
                b"not selected",
                "other.txt",
                "text/plain",
            ),
        ):
            self.materials[name] = self.release(
                self.write(
                    payload=payload(kind, title=title),
                    file_bytes=raw,
                    filename=filename,
                    media_type=media_type,
                )
            )

    def card(self, page, area, name):
        identifier = self.materials[name]["version_id"]
        return page.locator(f'#{area} article[data-version-id="{identifier}"]')

    def copy(self, page, name):
        """Read existing browser storage only; never inject or mutate app state."""
        return page.evaluate(
            """async ({root, id}) => {
                if (!(await caches.keys()).includes('fatwa-library-selected-v1')) return null;
                const cache = await caches.open('fatwa-library-selected-v1');
                const response = await cache.match(root + 'packets/' + id + '/');
                return response ? response.json() : null;
            }""",
            {"root": ROOT, "id": self.materials[name]["version_id"]},
        )

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)
            proof["screenshots"].append(f"{label}-{width}.png")

    def show(self, page, name):
        self.card(page, "saved", name).get_by_role(
            "button", name="قراءة النسخة المحلية", exact=True
        ).click()
        page.locator("#reader").wait_for(state="visible")
        page.wait_for_function(
            "title => document.querySelector('#reader h2')?.textContent === title",
            arg=self.materials[name]["payload"]["title"],
        )

    def save(self, page, name):
        self.card(page, "available", name).get_by_role(
            "button", name="حفظ هذه المادة على الجهاز", exact=True
        ).click()
        self.card(page, "saved", name).wait_for(state="visible")

    def archive(self, page, proof):
        for name in ("text", "video"):
            self.card(page, "available", name).locator('[name="version"]').check()
        self.assertFalse(
            self.card(page, "available", "uncached").locator('[name="version"]').is_checked()
        )
        with page.expect_download() as waiting:
            page.get_by_role("button", name="تنزيل أرشيف المواد المحددة", exact=True).click()
        downloaded = waiting.value
        self.assertIsNone(downloaded.failure())
        destination = OUT / "chosen-materials.zip"
        downloaded.save_as(str(destination))
        with zipfile.ZipFile(io.BytesIO(destination.read_bytes())) as archive:
            raw = archive.read("manifest.json")
            manifest = json.loads(raw)
            self.assertEqual(
                archive.read("manifest.sha256").decode(),
                sha256(raw).hexdigest() + "  manifest.json\n",
            )
            rows = manifest["materials"]
            self.assertEqual(len(rows), 2)
            expected = {
                self.materials["text"]["version_id"]: TEXT.encode(),
                self.materials["video"]["version_id"]: video(),
            }
            self.assertEqual({row["material"]["version_id"] for row in rows}, set(expected))
            for row in rows:
                self.assertEqual(
                    archive.read(row["archive_file"]), expected[row["material"]["version_id"]]
                )
            self.assertIn("أرشيف المواد المختارة", archive.read("index.html").decode())
        proof["archive"] = {"file": destination.name, "member_count": 2, "exact_originals": True}

    def test_native_pwa_selection_offline_bytes_revocation_and_shortened_expiry(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "trace": "trace.zip",
            "screenshots": [],
            "external_requests": [],
            "page_errors": [],
            "packet_requests": [],
        }
        origin, contexts = self.live_server_url, []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def observe(request):
                        parsed = urlsplit(request.url)
                        if (
                            parsed.scheme in {"http", "https"}
                            and parsed.netloc != urlsplit(origin).netloc
                        ):
                            proof["external_requests"].append("external-http")
                        if parsed.path.startswith(ROOT + "packets/"):
                            proof["packet_requests"].append(parsed.path)

                    def local_only(route):
                        url = route.request.url
                        parsed = urlsplit(url)
                        if (
                            parsed.scheme == "http" and parsed.netloc == urlsplit(origin).netloc
                        ) or url.startswith("blob:" + origin + "/"):
                            route.continue_()
                        else:
                            proof["external_requests"].append("blocked")
                            route.abort()

                    def context(label):
                        value = browser.new_context(
                            viewport={"width": 320, "height": 780}, accept_downloads=True
                        )
                        value.route("**/*", local_only)
                        value.on("request", observe)
                        value.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, value))
                        return value

                    local = context("offline")
                    page = local.new_page()
                    page.on(
                        "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                    )
                    response = page.goto(origin + ROOT)
                    self.assertEqual(response.status, 200)
                    page.wait_for_function("navigator.serviceWorker.controller !== null")
                    page.wait_for_function(
                        "document.querySelectorAll('#available article').length === 3"
                    )
                    self.assertEqual(page.locator("#saved article").count(), 0)
                    for name in self.materials:
                        self.assertIsNone(self.copy(page, name))
                    self.assertEqual(proof["packet_requests"], [])
                    proof["no_automatic_copies"] = True

                    cdp = local.new_cdp_session(page)
                    cdp.send("Page.enable")
                    manifest_result = cdp.send("Page.getAppManifest")
                    self.assertEqual(manifest_result.get("errors", []), [])
                    manifest = json.loads(manifest_result["data"])
                    self.assertEqual(manifest["start_url"], ROOT)
                    self.assertEqual(manifest["scope"], ROOT)
                    self.assertEqual(manifest["display"], "standalone")
                    installability = cdp.send("Page.getInstallabilityErrors")
                    self.assertEqual(installability.get("installabilityErrors", []), [])
                    proof["manifest"] = {
                        "url": manifest_result["url"],
                        "errors": [],
                        "installability_errors": [],
                    }
                    proof["service_worker"] = page.evaluate(
                        "({controlled: !!navigator.serviceWorker.controller, script: navigator.serviceWorker.controller.scriptURL, secure: window.isSecureContext})"
                    )
                    self.assertTrue(proof["service_worker"]["secure"])
                    self.assertEqual(proof["service_worker"]["script"], origin + ROOT + "sw.mjs")

                    for name in ("text", "video"):
                        self.save(page, name)
                    self.assertEqual(page.locator("#saved article").count(), 2)
                    self.assertIsNone(self.copy(page, "uncached"))
                    self.archive(page, proof)
                    self.capture(page, "selected-online", proof)

                    local.set_offline(True)
                    response = page.reload(wait_until="domcontentloaded")
                    self.assertEqual(response.status, 200)
                    page.wait_for_function(
                        "document.querySelectorAll('#saved article').length === 2"
                    )
                    self.assertFalse(page.evaluate("navigator.onLine"))
                    self.assertEqual(self.card(page, "saved", "uncached").count(), 0)
                    self.assertIsNone(self.copy(page, "uncached"))
                    self.show(page, "text")
                    self.assertEqual(page.locator("#reader pre").text_content(), TEXT)
                    self.assertEqual(
                        base64.b64decode(self.copy(page, "text")["file_base64"]), TEXT.encode()
                    )
                    self.capture(page, "text-offline", proof)
                    self.show(page, "video")
                    self.playable(page)
                    raw = base64.b64decode(self.copy(page, "video")["file_base64"])
                    self.assertEqual(raw, video())
                    shown_hash = page.evaluate(
                        """async () => {
                            const url = document.querySelector('#reader a[href^="blob:"]').href;
                            const raw = await (await fetch(url)).arrayBuffer();
                            return [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))]
                                .map(value => value.toString(16).padStart(2, '0')).join('');
                        }"""
                    )
                    self.assertEqual(shown_hash, sha256(video()).hexdigest())
                    proof["offline_video_sha256"] = shown_hash
                    self.capture(page, "video-offline", proof)
                    self.card(page, "saved", "text").get_by_role(
                        "button", name="حذف هذه النسخة", exact=True
                    ).click()
                    self.card(page, "saved", "text").wait_for(state="detached")
                    self.assertIsNone(self.copy(page, "text"))
                    self.assertEqual(self.card(page, "saved", "video").count(), 1)
                    proof["local_delete_preserved_other_copy"] = True

                    local.set_offline(False)
                    page.wait_for_function(
                        "navigator.onLine && document.querySelectorAll('#available article').length === 3"
                    )
                    publisher_context = context("source-editor")
                    publisher = publisher_context.new_page()
                    publisher.on(
                        "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                    )
                    self.login(publisher, "publisher")
                    self.open_library(publisher)
                    article = publisher.locator("article").filter(
                        has=publisher.get_by_role(
                            "heading", name=self.materials["video"]["payload"]["title"], exact=True
                        )
                    )
                    self.assertEqual(article.count(), 1)
                    self.submit(
                        publisher,
                        article.get_by_role("button", name="فتح المادة ونسخها", exact=True),
                    )
                    self.decision(publisher, "WITHDRAW")
                    page.locator("#refresh").click()
                    self.card(page, "saved", "video").wait_for(state="detached")
                    page.wait_for_function("document.querySelector('#reader').hidden")
                    self.assertIsNone(self.copy(page, "video"))
                    proof["withdrawal_removed_saved_and_active_copy"] = True

                    # A real server policy lease is shortened while this copy is
                    # open; no browser clock or cache is changed by the test.
                    self.card(page, "available", "text").wait_for(state="visible")
                    self.save(page, "text")
                    self.show(page, "text")
                    old_until = self.copy(page, "text")["expires_at"]
                    deadline = timezone.now() + timedelta(seconds=8)
                    with override_settings(
                        FATWA_LIBRARY_PREVIEW_POLICY=PreviewPolicy((), (), deadline, True)
                    ):
                        page.locator("#refresh").click()
                        page.wait_for_function(
                            """async ({root, id, oldUntil}) => {
                                const cache = await caches.open('fatwa-library-selected-v1');
                                const response = await cache.match(root + 'packets/' + id + '/');
                                if (!response) return false;
                                return Date.parse((await response.json()).expires_at) < Date.parse(oldUntil);
                            }""",
                            arg={
                                "root": ROOT,
                                "id": self.materials["text"]["version_id"],
                                "oldUntil": old_until,
                            },
                        )
                        shortened = self.copy(page, "text")["expires_at"]
                        self.assertLessEqual(datetime.fromisoformat(shortened), deadline)
                        self.assertFalse(
                            page.locator("#reader").evaluate("element => element.hidden")
                        )
                        page.wait_for_function(
                            "document.querySelector('#reader').hidden && document.querySelectorAll('#saved article').length === 0",
                            timeout=15000,
                        )
                        self.assertIsNone(self.copy(page, "text"))
                    proof["shortened_expiry"] = {
                        "previous": old_until,
                        "current": shortened,
                        "active_reader_cleared": True,
                    }
                    self.capture(page, "expired-local-copy", proof)

                    def observed():
                        case = Case.objects.get(pk=self.receipt["case_id"])
                        return (
                            case.revision,
                            case.evidence_version,
                            case.events.count(),
                            LibraryVersion.objects.count(),
                            LibraryDecision.objects.count(),
                        )

                    self.assertEqual(self.sync(observed), (1, 1, 1, 3, 10))
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                finally:
                    for label, value in contexts:
                        name = "trace.zip" if label == "offline" else "trace-source-editor.zip"
                        value.tracing.stop(path=str(OUT / name))
                        value.close()
                    browser.close()
                proof["status"] = "PASS"
        finally:
            (OUT / "result.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
            )
