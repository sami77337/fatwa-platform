"""Native browser journey connecting the new case, research and requester workflows."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.answer_media import services as media
from apps.casework import services as cases
from apps.casework.models import CaseEvent
from apps.content_reports.models import ContentReport, ReportEvent
from apps.content_reports.tests import FixtureAuthority
from apps.research_workspace.models import ResearchItem
from apps.research_workspace.tests import SETTINGS, ResearchFixture

FEATURES = {
    **SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "FATWA_CASE_ASSIGNMENTS_ENABLED": True,
    "FATWA_CASE_ORGANIZATION_ENABLED": True,
    "FATWA_RESEARCH_COLLECTIONS_ENABLED": True,
    "FATWA_CONTENT_REPORTS_ENABLED": True,
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}
OUT = Path(".local/qa/functional-completion/browser")


@override_settings(**FEATURES)
class FunctionalCompletionBrowserTests(ResearchFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        super().setUp()
        self.with_media()
        current = cases.read_case(**self.common)
        cases.record_decision(
            **self.common,
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        current = media.staff_snapshot(**self.common)
        media.release_private(
            **self.common,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=current["latest_package"]["sha256"],
            confirmed=True,
        )
        configured = override_settings(
            FATWA_CONTENT_REPORTS_AUTHORITY=FixtureAuthority(
                self.receipt["public_ref"], self.directory.provider_id, "editor"
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def sync(self, callback):
        def run():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=40)

    def form(self, page, action):
        # The connected journey contains duplicate navigation forms inside a
        # closed details element. Use the visible native control, not that hidden
        # earlier copy; keyboard activation must exercise an actual user path.
        form = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(form.count(), 1, f"visible native form missing: {action}")
        return form

    def submit(self, page, action, *, scope=None, code=200):
        form = self.form(scope or page, action)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button = form.locator('button:visible:not([type="button"])').first
            button.focus()
            button.press("Enter")
        self.assertIsNotNone(navigation.value, f"native form did not navigate: {action}")
        self.assertEqual(navigation.value.status, code, page.locator("main").inner_text()[:1000])
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_same_case_claim_metadata_collect_compare_report_and_human_resolution(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        before = cases.read_case(**self.common)
        event_count = CaseEvent.objects.count()
        external, errors, failed = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})
            requester_context = browser.new_context(viewport={"width": 320, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True)

            def route(r):
                parsed = urlsplit(r.request.url)
                if (
                    parsed.scheme != "http"
                    or parsed.netloc != urlsplit(self.live_server_url).netloc
                ):
                    external.append(r.request.url)
                    r.abort()
                else:
                    r.continue_()

            context.route("**/*", route)
            requester_context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: failed.append(r.url) if r.status >= 400 else None)
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                self.submit(page, "open")
                self.assertEqual(
                    page.locator("#mufti-case-reference").inner_text(), self.receipt["public_ref"]
                )
                self.submit(page, "assignment_claim")
                self.assertEqual(page.locator("#primary-mufti").inner_text(), "editor")
                self.capture(page, "claimed-case")
                self.submit(page, "organization_open")
                page.locator("#organization-tags").fill("مسافر\nملاحظة تنظيمية")
                page.locator("#organization-types").select_option(["MAKEUP", "EXPIATION"])
                page.locator("#organization-note").fill("STAFF ONLY organization note")
                self.submit(page, "organization_save")
                self.capture(page, "metadata-history")
                self.submit(page, "research_collections")
                page.locator("#new-collection-title").fill("مجموعة بحث اصطناعية خاصة")
                self.submit(page, "research_collection_create")
                self.submit(page, "research_open")
                page.locator("#kind").select_option("REFERENCE")
                page.locator("#edition").select_option(str(self.catalog_id))
                page.locator("#query").fill("فرع")
                self.submit(page, "research_search")
                self.submit(page, "research_save_search")
                self.form(page, "research_collection_save_search").locator('[name="title"]').fill(
                    "البحث في فروع الطبعة"
                )
                self.submit(page, "research_collection_save_search")
                self.submit(page, "research_collection_run_search")
                self.assertEqual(page.locator("#query").input_value(), "فرع")
                self.assertEqual(page.locator("#kind").input_value(), "REFERENCE")
                self.assertEqual(page.locator("#edition").input_value(), str(self.catalog_id))
                self.submit(
                    page,
                    "research_collect",
                    scope=page.locator(f'article[data-resource-id="{self.catalog_id}:2"]'),
                )
                self.form(page, "research_collection_add").locator('[name="note"]').fill(
                    "PRIVATE COLLECTION NOTE"
                )
                self.submit(page, "research_collection_add")
                self.submit(page, "research_open")
                # Opening research starts a new search. A saved search, unlike
                # this action, restores its exact filters. Do not rely on stale
                # reference filters while looking for a linked transcript.
                for field in ("#query", "#edition", "#part", "#page"):
                    self.assertEqual(page.locator(field).input_value(), "")
                self.assertEqual(page.locator("#kind").input_value(), "all")
                page.locator("#kind").select_option("TRANSCRIPT")
                page.locator("#query").fill(self.transcript_text[:30])
                self.submit(page, "research_search")
                self.submit(
                    page, "research_collect", scope=page.locator("article[data-resource-id]").first
                )
                self.submit(page, "research_collection_add")
                item_ids = page.locator("[data-saved-item]").evaluate_all(
                    "rows => rows.map(r=>r.dataset.savedItem)"
                )
                self.assertEqual(len(item_ids), 2)
                page.locator("#compare-first").select_option(item_ids[0])
                page.locator("#compare-second").select_option(item_ids[1])
                self.submit(page, "research_collection_compare")
                self.assertIn(
                    self.transcript_text, page.locator("#collection-comparison").inner_text()
                )
                self.assertIn(
                    "PRIVATE COLLECTION NOTE", page.locator("#collection-comparison").inner_text()
                )
                self.capture(page, "source-comparison")
                # A separate browser capability sees only the released answer.
                requester = requester_context.new_page()
                requester.on("pageerror", lambda e: errors.append(str(e)))
                requester.on(
                    "response", lambda r: failed.append(r.url) if r.status >= 400 else None
                )
                requester.goto(self.live_server_url + "/casework/status/")
                requester.locator("#portal-token").fill(self.receipt["token"])
                self.submit(requester, "unlock")
                for private in (
                    "STAFF ONLY",
                    "PRIVATE COLLECTION NOTE",
                    "مجموعة بحث اصطناعية خاصة",
                ):
                    self.assertNotIn(private, requester.content())
                requester.locator("#report-description").fill("المرفق يحتاج مراجعة تشغيل اصطناعية")
                media_target = requester.locator('#report-target option[value^="ANSWER_PART:"]')
                self.assertEqual(media_target.count(), 1)
                requester.locator("#report-target").select_option(
                    media_target.get_attribute("value")
                )
                requester.locator("#report-reason").select_option("BROKEN_MEDIA")
                self.submit(requester, "content_report")
                self.assertIn("استُلم بلاغك", requester.locator("main").inner_text())
                self.capture(requester, "requester-report")
                self.submit(page, "reports_open")
                self.form(page, "report_advance").locator('[name="transition"]').select_option(
                    "START"
                )
                self.form(page, "report_advance").locator('[name="action_note"]').fill(
                    "بدء تحقق بشري اصطناعي"
                )
                self.submit(page, "report_advance")
                self.assertIn("قيد المراجعة البشرية", page.locator("main").inner_text())
                self.form(page, "report_advance").locator('[name="transition"]').select_option(
                    "RESOLVE"
                )
                self.form(page, "report_advance").locator('[name="action_note"]').fill(
                    "سُجلت نتيجة المراجعة الفنية"
                )
                self.form(page, "report_advance").locator('[name="verification_note"]').fill(
                    "نتيجة تحقق بشرية اصطناعية لاختبار مسار البلاغ؛ لم يُعدّل المحتوى"
                )
                self.submit(page, "report_advance")
                self.assertIn("أغلق بعد تسجيل الإجراء والتحقق", page.locator("main").inner_text())
                self.capture(page, "human-report-resolution")
                requester.reload()
                self.assertIn(
                    "أغلق بعد تسجيل الإجراء والتحقق",
                    requester.locator("#content-reports").inner_text(),
                )
                self.assertNotIn("نتيجة تحقق بشرية اصطناعية", requester.content())
                self.assertEqual(self.sync(lambda: cases.read_case(**self.common)), before)
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), event_count)
                self.assertEqual(self.sync(lambda: ResearchItem.objects.count()), 2)
                self.assertEqual(self.sync(lambda: ContentReport.objects.count()), 1)
                self.assertEqual(
                    self.sync(
                        lambda: list(
                            ReportEvent.objects.order_by("sequence").values_list("action", "state")
                        )
                    ),
                    [("SUBMIT", "OPEN"), ("START", "IN_REVIEW"), ("RESOLVE", "RESOLVED")],
                )
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                self.assertEqual(failed, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser.version,
                            "sandbox": True,
                            "widths": [320, 1280],
                            "external_requests": external,
                            "page_errors": errors,
                            "http_failures": failed,
                            "case_state_unchanged": True,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                requester_context.close()
                context.close()
                browser.close()
