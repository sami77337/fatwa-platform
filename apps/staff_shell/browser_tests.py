"""Protected native installability and actual system dark-mode rendering."""

import json
import os
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.case_attachments.tests import new_case
from apps.public_answer_media.test_support import FEATURES as PUBLIC_FEATURES
from apps.public_answer_media.test_support import MediaFixture
from tests.casework.test_http import Directory

ROOT = Path(".local/qa/functional-continuation")


class BrowserHelpers:
    def wait_native(self, page, expression):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if page.evaluate(expression):
                return
            page.wait_for_timeout(50)
        self.fail("native browser state was not observed")

    def capture(self, page, folder, name, proof):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            target = folder / f"{name}-{width}.png"
            page.screenshot(path=str(target), full_page=True)
            proof["screenshots"].append(target.name)

    def restrict(self, context, proof):
        def route(request):
            url = urlsplit(request.request.url)
            if url.scheme == "http" and url.netloc == urlsplit(self.live_server_url).netloc:
                request.continue_()
            else:
                proof["external_requests"].append(request.request.url)
                request.abort()
        context.route("**/*", route)


@override_settings(FATWA_CASEWORK_WEB_ENABLED=True, FATWA_STAFF_PWA_ENABLED=True,
                   ROOT_URLCONF="config.campaign_urls")
class StaffPWABrowserTests(BrowserHelpers, LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        self.receipt = new_case()
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        config = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        config.enable()
        self.addCleanup(config.disable)

    def test_installable_staff_scope_requires_live_authorization_and_never_caches_cases(self):
        from playwright.sync_api import sync_playwright
        folder = ROOT / "staff-pwa-browser"
        folder.mkdir(parents=True, exist_ok=True)
        proof = {"status": "ERROR", "sandbox": True, "widths": [320, 1280],
                 "screenshots": [], "trace": "trace.zip", "page_errors": [], "external_requests": []}
        try:
            with tempfile.TemporaryDirectory(prefix="staff-pwa-profile-") as profile, sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=profile, executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    headless=True, chromium_sandbox=True, args=["--disable-dev-shm-usage"],
                    viewport={"width": 320, "height": 900},
                )
                self.restrict(context, proof)
                context.tracing.start(screenshots=True, snapshots=True)
                try:
                    page = context.new_page()
                    page.on("pageerror", lambda error: proof["page_errors"].append(str(error)))
                    self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
                    page.locator("#credential").fill(self.directory.credential)
                    with page.expect_navigation(wait_until="domcontentloaded") as authenticated:
                        page.get_by_role("button", name="دخول المكتب", exact=True).click()
                    self.assertEqual(authenticated.value.status, 200)
                    self.assertNotIn("x-staff-offline", authenticated.value.headers)
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.get_by_role("button", name=self.receipt["public_ref"], exact=True).click()
                    self.assertIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    self.wait_native(page, "() => Boolean(navigator.serviceWorker.controller)")
                    scope = page.evaluate("async () => (await navigator.serviceWorker.ready).scope")
                    self.assertEqual(scope, self.live_server_url + "/casework/staff/")
                    cdp = context.new_cdp_session(page)
                    manifest = cdp.send("Page.getAppManifest")
                    self.assertEqual(manifest.get("errors", []), [])
                    errors = cdp.send("Page.getInstallabilityErrors").get("installabilityErrors", [])
                    self.assertEqual(errors, [])
                    proof["manifest"] = {"scope": scope, "installability_errors": errors}
                    self.capture(page, folder, "staff-installed-shell", proof)
                    self.assertEqual(page.evaluate("async () => await caches.keys()"), [])
                    context.set_offline(True)
                    response = page.goto(self.live_server_url + "/casework/staff/")
                    self.assertEqual(response.status, 503)
                    self.assertEqual(response.headers.get("x-staff-offline"), "network-required")
                    self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    self.assertIn("يلزم الاتصال", page.locator("h1").inner_text())
                    self.assertEqual(page.locator("form").count(), 0)
                    self.assertEqual(page.evaluate("async () => await caches.keys()"), [])
                    self.capture(page, folder, "offline-no-private-data", proof)
                    self.directory.current = replace(self.directory.current, active=False)
                    context.set_offline(False)
                    self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 403)
                    self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    proof.update(no_case_cache=True, offline_private_actions_unavailable=True,
                                 reconnected_revoked_identity_denied=True, persistent_profile=True)
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    proof["status"] = "PASS"
                finally:
                    context.tracing.stop(path=str(folder / "trace.zip"))
                    context.close()
        finally:
            (folder / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")


def contrast(first, second):
    def luminance(value):
        colors = [int(c) / 255 for c in re.findall(r"\d+", value)[:3]]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in colors]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))
    ordered = sorted((luminance(first), luminance(second)))
    return (ordered[1] + 0.05) / (ordered[0] + 0.05)


@override_settings(**PUBLIC_FEATURES)
class DarkModeBrowserTests(BrowserHelpers, MediaFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_system_theme_switch_preserves_published_content_with_readable_dark_surfaces(self):
        from playwright.sync_api import sync_playwright
        folder = ROOT / "dark-mode-browser"
        folder.mkdir(parents=True, exist_ok=True)
        proof = {"status": "ERROR", "sandbox": True, "widths": [320, 1280],
                 "screenshots": [], "trace": "trace.zip", "page_errors": [], "external_requests": [], "contrast": {}}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                                                     chromium_sandbox=True, args=["--disable-dev-shm-usage"])
                context = browser.new_context(viewport={"width": 320, "height": 900}, color_scheme="light")
                context.tracing.start(screenshots=True, snapshots=True)
                self.restrict(context, proof)
                try:
                    page = context.new_page()
                    page.on("pageerror", lambda error: proof["page_errors"].append(str(error)))
                    self.assertEqual(page.goto(self.live_server_url + f"/library-preview/editions/{self.publication.pk}/").status, 200)
                    text = page.locator("main").inner_text()
                    light = page.locator("html").evaluate("e => getComputedStyle(e).backgroundColor")
                    self.capture(page, folder, "public-light", proof)
                    page.emulate_media(color_scheme="dark")
                    self.wait_native(page, "() => matchMedia('(prefers-color-scheme: dark)').matches")
                    self.assertEqual(page.locator("main").inner_text(), text)
                    dark = page.locator("html").evaluate("e => getComputedStyle(e).backgroundColor")
                    self.assertNotEqual(dark, light)
                    for selector, background in (("html", "html"), ("article", "article"), ("main a", "html")):
                        foreground = page.locator(selector).first.evaluate("e => getComputedStyle(e).color")
                        backdrop = page.locator(background).first.evaluate("e => getComputedStyle(e).backgroundColor")
                        ratio = contrast(foreground, backdrop)
                        self.assertGreaterEqual(ratio, 4.5)
                        proof["contrast"][selector] = round(ratio, 3)
                    self.capture(page, folder, "public-dark", proof)
                    self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
                    self.assertEqual(page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(17, 28, 32)")
                    self.capture(page, folder, "private-login-dark", proof)
                    page.emulate_media(color_scheme="light")
                    self.assertNotEqual(page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(17, 28, 32)")
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof.update(status="PASS", actual_system_preference=True, published_text_unchanged=True, light_mode_restored=True)
                finally:
                    context.tracing.stop(path=str(folder / "trace.zip"))
                    context.close()
                    browser.close()
        finally:
            (folder / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
