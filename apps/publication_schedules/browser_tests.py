"""Real native scheduling, cancellation, due worker and exact public edition."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.library_preview.policy import PreviewPolicy, PublicationGrant

from .models import PublicationSchedule
from .test_support import CREDENTIAL, FEATURES, ScheduleFixture

OUT = Path(".local/qa/functional-continuation/publication-schedules-browser")
BROWSER_FEATURES = {
    **FEATURES,
    "FATWA_LIBRARY_PREVIEW_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    "MIDDLEWARE": [
        "apps.library_preview.guard.PreviewCompositionGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
}


@override_settings(**BROWSER_FEATURES)
class PublicationScheduleBrowserTests(ScheduleFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
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

    def open_desk(self, page):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        self.submit(page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True))
        self.submit(page, page.get_by_role("button", name="مواعيد نشر النسخ المراجعة", exact=True))

    def schedule_native(self, page, edition_id):
        form = page.locator("#publication-schedule")
        at = (
            (timezone.now() + timedelta(minutes=5))
            .astimezone(ZoneInfo("Asia/Amman"))
            .replace(second=0, microsecond=0)
        )
        form.locator('[name="edition_id"]').select_option(edition_id)
        form.locator('[name="scheduled_at"]').fill(at.strftime("%Y-%m-%dT%H:%M"))
        form.locator('[name="target"]').select_option("WEBSITE_PREVIEW")
        form.locator('[name="reason"]').fill("اختيار بشري صريح للنسخة والموعد والوجهة في الاختبار")
        form.locator('[name="confirmed"]').check()
        self.submit(page, form.locator("button"))
        article = page.locator("#schedule-history article").first
        self.assertEqual(
            article.locator("[data-schedule-state]").get_attribute("data-schedule-state"),
            "SCHEDULED",
        )
        return article.get_attribute("data-schedule")

    def action(self, page, identifier, action):
        article = page.locator(f'article[data-schedule="{identifier}"]')
        form = article.locator(f'form:has(input[name="action"][value="{action}"])')
        form.locator('[name="confirmed"]').check()
        self.submit(page, form.locator("button"))

    def capture(self, page, name, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            target = OUT / f"{name}-{width}.png"
            page.screenshot(path=str(target), full_page=True)
            proof["screenshots"].append(target.name)

    def test_native_exact_future_schedule_cancel_due_publication_and_changed_authority_hold(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "traces": [],
            "trace": "trace.zip",
            "page_errors": [],
            "external_requests": [],
            "test_clock": "explicit due-time fixture; actual native worker and database are unchanged",
        }
        edition = self.sync(lambda: PublicationEdition.objects.get(pk=self.edition["id"]))
        policy = PreviewPolicy(
            (PublicationGrant(str(edition.pk), edition.content_sha256),),
            (),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        public_url = self.live_server_url + f"/library-preview/editions/{edition.pk}/"
        contexts = []
        try:
            with (
                override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy),
                sync_playwright() as playwright,
            ):
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def context_for(label):
                        context = browser.new_context(viewport={"width": 320, "height": 780})

                        def local_only(route):
                            if (
                                urlsplit(route.request.url).scheme != "http"
                                or urlsplit(route.request.url).netloc
                                != urlsplit(self.live_server_url).netloc
                            ):
                                proof["external_requests"].append("blocked")
                                route.abort()
                            else:
                                route.continue_()

                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((label, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    page, public = context_for("trace"), context_for("public")
                    self.assertEqual(public.goto(public_url).status, 404)
                    self.assertEqual(
                        page.goto(self.live_server_url + "/casework/staff/login/").status, 200
                    )
                    page.locator("#credential").fill(CREDENTIAL)
                    self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))
                    self.open_desk(page)
                    cancelled = self.schedule_native(page, str(edition.pk))
                    self.action(page, cancelled, "ps_cancel")
                    self.assertEqual(
                        page.locator(
                            f'article[data-schedule="{cancelled}"] [data-schedule-state]'
                        ).get_attribute("data-schedule-state"),
                        "CANCELLED",
                    )
                    selected = self.schedule_native(page, str(edition.pk))
                    self.action(page, selected, "ps_run")
                    self.assertEqual(
                        page.locator(
                            f'article[data-schedule="{selected}"] [data-schedule-state]'
                        ).get_attribute("data-schedule-state"),
                        "SCHEDULED",
                    )
                    self.assertEqual(public.goto(public_url).status, 404)
                    self.capture(page, "scheduled-exact-version", proof)
                    due = self.sync(
                        lambda: PublicationSchedule.objects.get(pk=selected).scheduled_at
                    )
                    with patch(
                        "django.utils.timezone.now", return_value=due + timedelta(seconds=1)
                    ):
                        self.action(page, selected, "ps_run")
                        self.assertEqual(
                            page.locator(
                                f'article[data-schedule="{selected}"] [data-schedule-state]'
                            ).get_attribute("data-schedule-state"),
                            "PUBLISHED",
                        )
                        self.assertEqual(public.goto(public_url).status, 200)
                        self.assertIn(edition.body, public.locator("body").inner_text())
                        self.assertNotIn("PRIVATE", public.locator("body").inner_text())
                        self.capture(public, "published-selected-edition", proof)
                    newer = self.sync(self.new_edition)
                    self.open_desk(page)
                    held = self.schedule_native(page, newer["id"])
                    self.authority.denied.add("EXECUTE")
                    due = self.sync(lambda: PublicationSchedule.objects.get(pk=held).scheduled_at)
                    with patch(
                        "django.utils.timezone.now", return_value=due + timedelta(seconds=1)
                    ):
                        self.action(page, held, "ps_run")
                    self.assertEqual(
                        page.locator(
                            f'article[data-schedule="{held}"] [data-schedule-state]'
                        ).get_attribute("data-schedule-state"),
                        "HOLD",
                    )
                    approved = self.sync(
                        lambda: list(
                            PublicationAction.objects.filter(action="APPROVE").values_list(
                                "edition_id", flat=True
                            )
                        )
                    )
                    self.assertEqual(approved, [edition.pk])
                    self.capture(page, "current-grant-hold", proof)
                    proof.update(
                        exact_edition_sha256=edition.content_sha256,
                        cancelled_before_due=True,
                        no_early_publication=True,
                        exact_due_publication=True,
                        revoked_current_grant_held=True,
                        approved_editions=1,
                        browser_version=browser.version,
                    )
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof["status"] = "PASS"
                finally:
                    for label, context in contexts:
                        name = label + ".zip"
                        context.tracing.stop(path=str(OUT / name))
                        proof["traces"].append(name)
                        context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
