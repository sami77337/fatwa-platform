"""Protected browser proof through the integrated native campaign, without bypasses."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case

from .models import LifecycleEvent
from .tests import FEATURES, Fixture

OUT = Path(".local/qa/functional-completion/lifecycle-browser")


@override_settings(
    **{
        **FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_REQUESTER_PORTAL_ENABLED": True,
        "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    }
)
class LifecycleBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        # Only fixture preparation is programmatic. Every lifecycle mutation and
        # the later requester followup is submitted through a visible native form.
        self.approved()

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as workers:
            return workers.submit(work).result(timeout=30)

    def form(self, page, action, *, host=None, navigation=False):
        form = (host or page).locator(f'form:visible:has([name="action"][value="{action}"])')
        if navigation:
            self.assertGreaterEqual(form.count(), 1, "missing integrated native navigation")
            return form.first
        self.assertEqual(form.count(), 1, "ambiguous native lifecycle action: " + action)
        return form

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.press("Enter")
        self.assertIsNotNone(navigation.value)
        self.assertEqual(navigation.value.status, 200)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def send(self, page, form):
        self.submit(page, form.locator('button:visible:not([type="button"])'))

    def act(self, page, action):
        form = self.form(page, "lc_" + action.lower())
        form.locator('[name="reason"]').fill("سبب بشري اصطناعي واضح: " + action)
        form.locator('[name="confirm"]').check()
        if action == "CLOSE":
            choice = form.locator('[name="without_delivery"]')
            self.assertEqual(choice.get_attribute("type"), "checkbox")
            self.assertFalse(choice.is_checked())
            choice.check()
        self.send(page, form)

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{label}-{width}.png"), full_page=True)
            proof["screenshots"].append(f"{label}-{width}.png")

    def test_native_close_archive_restore_reopen_and_requester_followup(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "external_requests": [],
            "page_errors": [],
            "owner_points": [385, 386],
        }
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
                    context = browser.new_context(viewport={"width": 320, "height": 780})
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)

                    def local_only(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                            proof["external_requests"].append("blocked")
                            route.abort()
                        else:
                            route.continue_()

                    context.route("**/*", local_only)
                    page = context.new_page()
                    page.on(
                        "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                    )
                    page.goto(origin + "/casework/staff/login/")
                    page.locator("#credential").fill(self.directory.credentials["mufti-a"])
                    self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))
                    self.send(page, self.form(page, "lc_inbox", navigation=True))
                    self.assertEqual(page.locator("#lc-state").input_value(), "ARCHIVED")
                    page.locator("#lc-state").select_option("ALL")
                    page.locator("#lc-query").fill(self.receipt["public_ref"])
                    self.send(page, self.form(page, "lc_filter"))
                    article = page.locator(
                        f'article[data-lifecycle-case="{self.receipt["public_ref"]}"]'
                    )
                    self.send(page, self.form(page, "lc_open", host=article))
                    self.assertEqual(
                        page.locator("#lifecycle-state").get_attribute("data-state"), "OPEN"
                    )
                    self.act(page, "CLOSE")
                    self.assertEqual(
                        page.locator("#lifecycle-state").get_attribute("data-state"), "CLOSED"
                    )
                    self.assertIn(
                        "دون ادعاء توصيل", page.locator("#lifecycle-history").inner_text()
                    )
                    self.act(page, "ARCHIVE")
                    self.send(page, self.form(page, "lc_inbox", navigation=True))
                    self.assertEqual(page.locator("#lc-query").input_value(), "")
                    self.assertEqual(page.locator("#lc-state").input_value(), "ARCHIVED")
                    article = page.locator(
                        f'article[data-lifecycle-case="{self.receipt["public_ref"]}"]'
                    )
                    self.assertEqual(article.count(), 1)
                    self.capture(page, "archive-list", proof)
                    self.send(page, self.form(page, "lc_open", host=article))
                    self.act(page, "RESTORE")
                    self.assertEqual(
                        page.locator("#lifecycle-state").get_attribute("data-state"), "CLOSED"
                    )
                    self.act(page, "REOPEN")
                    self.assertEqual(
                        page.locator("#lifecycle-state").get_attribute("data-state"), "OPEN"
                    )
                    self.act(page, "CLOSE")
                    self.act(page, "ARCHIVE")
                    self.capture(page, "archived-history", proof)

                    requester = browser.new_context(viewport={"width": 320, "height": 780})
                    requester.route("**/*", local_only)
                    private = requester.new_page()
                    private.on(
                        "pageerror", lambda error: proof["page_errors"].append(type(error).__name__)
                    )
                    private.goto(origin + "/casework/status/")
                    private.locator("#portal-token").fill(self.receipt["token"])
                    self.submit(
                        private, private.get_by_role("button", name="فتح قضيتي", exact=True)
                    )
                    private.locator("#portal-followup").fill(
                        "تعقيب صحيح يعيد فتح القضية المؤرشفة نفسها"
                    )
                    self.send(private, private.locator("#portal-reply-form"))
                    self.assertIn(self.receipt["public_ref"], private.locator("main").inner_text())
                    self.assertNotIn("سبب بشري اصطناعي واضح", private.locator("main").inner_text())
                    requester.close()

                    # Returning through the normal queue proves the canonical
                    # followup hook and queue filter integration, without a DB fixup.
                    response = page.goto(origin + "/casework/staff/")
                    self.assertEqual(response.status, 200)
                    self.submit(
                        page,
                        page.get_by_role("button", name=self.receipt["public_ref"], exact=True),
                    )
                    self.send(page, self.form(page, "lc_open", navigation=True))
                    self.assertEqual(
                        page.locator("#lifecycle-state").get_attribute("data-state"), "OPEN"
                    )
                    self.assertIn(
                        "إعادة فتح بسبب تعقيب جديد", page.locator("#lifecycle-history").inner_text()
                    )
                    self.capture(page, "followup-reopened", proof)

                    def observed():
                        case = Case.objects.get(pk=self.receipt["case_id"])
                        return (
                            case.evidence_version,
                            case.public_ref,
                            case.answers.count(),
                            case.decisions.count(),
                            case.approved_answer_id,
                            LifecycleEvent.objects.filter(case=case).count(),
                        )

                    self.assertEqual(
                        self.sync(observed), (2, self.receipt["public_ref"], 1, 1, None, 7)
                    )
                    self.assertEqual(proof["external_requests"], [])
                    self.assertEqual(proof["page_errors"], [])
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                    context.close()
                    proof["status"] = "PASS"
                finally:
                    browser.close()
        finally:
            (OUT / "result.json").write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
            )
