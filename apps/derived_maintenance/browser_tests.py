"""One protected journey through actual campaign routes and native current readers."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.ai_gateway.models import CandidateBatch
from apps.canonical_search.models import SearchDocument
from apps.casework import services as cases
from apps.casework.models import Case
from apps.operational_workspace import browser_tests as operational_browser

from . import recovery_support, views
from .models import DerivativeClear, DerivativeRebuild
from .test_support import FEATURES, Fixture

OUT = Path(".local/qa/functional-continuation/derived-maintenance-browser")


@override_settings(
    **{
        **FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    }
)
class DerivedMaintenanceBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = operational_browser.OperationalWorkspaceBrowserTests.sync
    submit = operational_browser.OperationalWorkspaceBrowserTests.submit

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def inspect_native(self, page, kind):
        self.assertEqual(page.goto(self.live_server_url + views.STAFF_PATH).status, 200)
        identifier = self.built["generation_id"] if kind == "SEARCH_INDEX" else self.run["id"]
        self.submit(page, page.locator(f'[data-target="{identifier}"] button'))

    def preview_native(self, page, *, fragment=""):
        form = page.locator("#derived-preview-form")
        self.assertEqual(form.count(), 1)
        form.locator('[name="reason"]').fill("إجراء صريح للمشتق مع إبقاء العمل البشري")
        if fragment:
            form.locator('[name="fragment"]').fill(fragment)
        self.submit(page, form.locator("button"))
        self.assertEqual(page.locator("#derived-confirm-form").count(), 1)

    def confirm_native(self, page, action):
        page.locator('#derived-confirm-form [name="confirmed"]').check()
        self.submit(page, page.locator("#derived-confirm-form button"))
        self.assertEqual(page.locator(f'[data-result="{action}"]').count(), 1)

    def test_native_clear_regenerate_current_sources_and_preserved_human_approval(self):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected derivative evidence requires FATWA_BROWSER_SANDBOX=1")
        from playwright.sync_api import sync_playwright

        citation = self.save_citations()
        self.review_citations(citation)
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            answer_id=citation["answer_id"],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            action="APPROVE",
            note="اعتماد بشري اصطناعي يبقى بعد إدارة المشتقات",
        )
        pins = {"case": {"case_id": self.receipt["case_id"]}}
        originals = recovery_support.originals(pins)
        OUT.mkdir(parents=True, exist_ok=True)
        for name in ("result.json", "trace.zip", "navigation.json"):
            (OUT / name).unlink(missing_ok=True)
        errors, external, navigation = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER") or None,
                headless=True,
                chromium_sandbox=True,
            )
            context = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route(request):
                address = urlsplit(request.request.url)
                if (
                    address.scheme != "http"
                    or address.netloc != urlsplit(self.live_server_url).netloc
                ):
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            def record_response(response):
                if response.request.is_navigation_request():
                    navigation.append(
                        {
                            "method": response.request.method,
                            "path": urlsplit(response.url).path,
                            "status": response.status,
                        }
                    )

            context.route("**/*", route)
            page.on("response", record_response)
            try:
                self.assertEqual(
                    page.goto(self.live_server_url + "/casework/staff/login/").status, 200
                )
                page.locator('[name="credential"]').fill(
                    "synthetic-editor-credential-32-characters"
                )
                self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))
                self.inspect_native(page, "SEARCH_INDEX")
                self.assertEqual(page.locator('[data-state="PRESENT"]').count(), 1)
                self.preview_native(page)
                self.assertEqual(self.sync(lambda: DerivativeClear.objects.count()), 0)
                self.capture(page, "review-before-clear")
                self.confirm_native(page, "CLEAR")
                self.assertFalse(
                    self.sync(
                        lambda: SearchDocument.objects.filter(
                            generation_id=self.built["generation_id"]
                        ).exists()
                    )
                )
                self.inspect_native(page, "SEARCH_INDEX")
                self.assertEqual(page.locator('[data-state="CLEARED"]').count(), 1)
                self.preview_native(page)
                self.confirm_native(page, "REBUILD")
                search_child = page.locator("[data-child-id]").inner_text()
                self.assertNotEqual(search_child, self.built["generation_id"])
                self.submit(page, page.locator("#derived-open-search button"))
                page.locator("#canonical-query").fill("عبارة")
                page.locator("#canonical-mode").select_option("FTS")
                self.submit(
                    page,
                    page.locator('form:has([name="action"][value="cs_search"]) button'),
                )
                self.assertEqual(page.locator('.canonical-hit[data-kind="ANSWER"]').count(), 1)
                self.submit(page, page.locator('.canonical-hit[data-kind="ANSWER"] form button'))
                self.assertEqual(
                    page.locator("#canonical-source-text").text_content(), self.answer_text
                )
                self.capture(page, "rebuilt-search-human-source")

                self.inspect_native(page, "AI_CANDIDATES")
                self.assertEqual(page.locator('[data-state="PRESENT"]').count(), 1)
                self.preview_native(page)
                self.confirm_native(page, "CLEAR")
                self.assertFalse(
                    self.sync(lambda: CandidateBatch.objects.filter(run_id=self.run["id"]).exists())
                )
                self.inspect_native(page, "AI_CANDIDATES")
                self.assertEqual(page.locator('[data-state="CLEARED"]').count(), 1)
                self.preview_native(page, fragment="عبارة محددة")
                self.confirm_native(page, "REBUILD")
                ai_child = page.locator("[data-child-id]").inner_text()
                self.assertNotEqual(ai_child, self.run["id"])
                self.assertEqual(
                    page.locator("#derived-rebuilt-candidates").get_attribute("data-run-id"),
                    ai_child,
                )
                self.assertEqual(
                    page.locator("#derived-rebuilt-candidates blockquote").text_content(),
                    self.source_text,
                )
                self.assertEqual(page.locator("#derived-open-citations button").count(), 1)
                self.capture(page, "regenerated-candidates-current-original")
                self.assertEqual(len(self.ai_provider.calls), 2)
                self.assertEqual(
                    self.sync(
                        lambda: (
                            DerivativeClear.objects.count(),
                            DerivativeRebuild.objects.count(),
                        )
                    ),
                    (2, 2),
                )
                self.maintenance_authority.denied.add(("editor", "ENTER"))
                self.assertEqual(page.goto(self.live_server_url + views.STAFF_PATH).status, 409)
                self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                self.maintenance_authority.denied.clear()
                self.inspect_native(page, "AI_CANDIDATES")
                self.assertEqual(page.locator('[data-state="CLEARED"]').count(), 1)
                self.assertIn(ai_child, page.locator("body").inner_text())
                self.assertNotIn(self.source_text, page.locator("body").inner_text())
                self.assertEqual(self.sync(lambda: recovery_support.originals(pins)), originals)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
            finally:
                failed = sys.exc_info()[0] is not None
                cleanup_errors = []
                try:
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                except Exception as exc:
                    cleanup_errors.append("trace: " + type(exc).__name__)
                try:
                    context.close()
                    browser.close()
                except Exception as exc:
                    cleanup_errors.append("browser: " + type(exc).__name__)
                try:
                    (OUT / "navigation.json").write_text(
                        json.dumps(
                            {"navigation": navigation, "cleanup_errors": cleanup_errors},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                except Exception as exc:
                    cleanup_errors.append("navigation: " + type(exc).__name__)
                if not failed:
                    self.assertEqual(cleanup_errors, [])
        (OUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "native_journeys": 1,
                    "actual_role": "MUFTI",
                    "independent_administrative_mandate": True,
                    "payload_owners": ["SearchDocument", "CandidateBatch"],
                    "actual_payload_clearance": True,
                    "new_generation_and_request": True,
                    "current_native_sources_opened": True,
                    "human_edits_and_approval_preserved": True,
                    "positive_audit_after_denial": True,
                    "central_ai_gateway": True,
                    "provider_mode": "SYNTHETIC",
                    "semantic_search": "NOT_IMPLEMENTED",
                    "page_errors": errors,
                    "external_requests": external,
                    "widths": [320, 1280],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
