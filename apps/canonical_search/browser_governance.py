"""Two real staff sessions review a native dictionary and compare live PostgreSQL search."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings
from django.utils.html import escape

from apps.casework.models import CaseEvent, CaseSource

from .browser_tests import CanonicalSearchBrowserTests
from .governance_test_support import CREDENTIALS, FEATURES, TERM, GovernanceFixture
from .models import ShadowComparison, SynonymDecision, SynonymRevision

OUT = Path(".local/qa/functional-continuation/search-governance-browser")


@override_settings(**FEATURES)
class SearchGovernanceBrowserTests(GovernanceFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = CanonicalSearchBrowserTests.sync
    form = CanonicalSearchBrowserTests.form
    submit = CanonicalSearchBrowserTests.submit

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def enter(self, page, subject):
        page.goto(self.live_server_url + "/casework/staff/login/")
        page.locator("#credential").fill(CREDENTIALS[subject])
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.assertEqual(navigation.value.status, 200)
        self.reopen(page)

    def reopen(self, page):
        page.goto(self.live_server_url + "/casework/staff/")
        self.submit(page, "open")
        self.submit(page, "cs_open")
        self.submit(page, "cs_dictionary_open")
        self.assertEqual(page.locator("#governance-case").inner_text(), self.receipt["public_ref"])

    def review_form(
        self,
        page,
        *,
        number=1,
        decision="APPROVE",
        note="راجعت ألفاظ الاختبار وأثرها على المصدر المحدد",
    ):
        form = page.locator(f'.dictionary-version[data-number="{number}"] .dictionary-review-form')
        form.locator('[name="decision"]').select_option(decision)
        form.locator('[name="note"]').fill(note)
        form.locator('[name="ttl"]').fill("60" if decision == "APPROVE" else "0")
        form.locator('[name="confirm"]').check()
        return form

    def test_native_versioned_dictionary_independent_review_actual_fts_shadow_and_retirement(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        before = CaseEvent.objects.count()
        errors, external = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            contexts = [
                browser.new_context(viewport={"width": 320, "height": 900}) for _ in range(2)
            ]

            def route(request):
                url = urlsplit(request.request.url)
                if url.scheme != "http" or url.netloc != urlsplit(self.live_server_url).netloc:
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            for context in contexts:
                context.route("**/*", route)
                context.tracing.start(screenshots=True, snapshots=True)
            editor, reviewer = [context.new_page() for context in contexts]
            for page in (editor, reviewer):
                page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                self.enter(editor, "editor")
                editor.locator("#dictionary-editor > summary").click()
                editor.locator("#dictionary-title").fill("قاموس بشري اصطناعي لاختبار الواجهة")
                editor.locator("#dictionary-provenance").fill(
                    "ألفاظ تجريبية أنشئت لهذا الاختبار فقط"
                )
                editor.locator("#entry-0-key").fill("synthetic-one")
                editor.locator("#entry-0-term").fill(TERM)
                editor.locator("#entry-0-alternatives").fill("المعاملات")
                self.submit(editor, "cs_dictionary_save")
                self.assertEqual(self.sync(lambda: SynonymRevision.objects.count()), 1)
                editor.locator("#preview-1").fill(TERM + "\nالمعاملات")
                self.submit(editor, "cs_dictionary_preview")
                self.assertEqual(
                    editor.locator(".preview-query")
                    .first.locator(".preview-baseline-count")
                    .inner_text(),
                    "0",
                )
                self.assertEqual(
                    editor.locator(".preview-query")
                    .first.locator(".preview-candidate-count")
                    .inner_text(),
                    "2",
                )
                self.capture(editor, "native-impact-preview")
                self.submit(editor, "cs_dictionary_review", form=self.review_form(editor), code=409)
                self.assertEqual(self.sync(lambda: SynonymDecision.objects.count()), 0)
                self.enter(reviewer, "other")
                self.submit(reviewer, "cs_dictionary_preview_open")
                self.assertEqual(reviewer.locator(".preview-query").count(), 2)
                self.submit(reviewer, "cs_dictionary_review", form=self.review_form(reviewer))
                self.assertEqual(
                    reviewer.locator('.dictionary-version[data-number="1"]').get_attribute(
                        "data-state"
                    ),
                    "APPROVE",
                )
                self.capture(reviewer, "independent-review")

                self.reopen(editor)
                editor.locator("#dictionary-query-1").fill(TERM)
                self.submit(editor, "cs_dictionary_search")
                self.assertEqual(editor.locator(".dictionary-hit").count(), 2)
                self.assertIn("other", editor.locator("#dictionary-results").inner_text())
                self.capture(editor, "actual-dictionary-search")
                original = self.submit(
                    editor,
                    "cs_source",
                    form=editor.locator('.dictionary-hit[data-kind="QUESTION"] form'),
                )
                self.assertIn(escape(self.question).encode(), original.body())
                self.assertEqual(
                    editor.locator("#canonical-source-text").text_content(),
                    self.question.replace("\r\n", "\n").replace("\r", "\n"),
                )

                self.submit(editor, "cs_dictionary_open")
                editor.locator("#shadow-query-1").fill(TERM)
                self.submit(editor, "cs_shadow_run")
                self.assertEqual(editor.locator("#shadow-baseline-count").inner_text(), "0")
                self.assertEqual(editor.locator("#shadow-candidate-count").inner_text(), "2")
                self.assertEqual(editor.locator(".shadow-candidate-hit").count(), 2)
                comparison_id = editor.locator("#shadow-comparison").get_attribute(
                    "data-comparison-id"
                )
                observed = self.sync(lambda: ShadowComparison.objects.get(pk=comparison_id))
                self.assertEqual(observed.baseline["total"], 0)
                self.assertEqual(observed.candidate["total"], 2)
                self.assertEqual(observed.candidate_status, "OK")
                self.capture(editor, "real-shadow-comparison")
                self.submit(editor, "cs_open")
                editor.locator("#canonical-query").fill(TERM)
                self.submit(editor, "cs_search")
                self.assertEqual(editor.locator(".canonical-hit").count(), 0)
                self.capture(editor, "baseline-remains-unchanged")

                self.submit(editor, "cs_dictionary_open")
                editor.locator("#dictionary-editor > summary").click()
                editor.locator("#entry-0-key").fill("synthetic-new")
                editor.locator("#entry-0-term").fill("بديلمصطنع")
                editor.locator("#entry-0-alternatives").fill("الزكاة")
                editor.locator("#map-0-kind").select_option("RENAMED")
                editor.locator("#map-0-targets").fill("synthetic-new")
                editor.locator("#map-0-reason").fill(
                    "ربط تغيير تسمية اصطناعي مع حفظ النسخة السابقة"
                )
                self.submit(editor, "cs_dictionary_save")
                self.assertEqual(editor.locator(".dictionary-version").count(), 2)
                self.assertEqual(
                    editor.locator('.dictionary-version[data-number="2"]').get_attribute(
                        "data-state"
                    ),
                    "DRAFT",
                )
                self.capture(editor, "version-lineage")
                second = self.sync(lambda: SynonymRevision.objects.get(number=2))
                self.assertEqual(second.mapping[0]["from"], "synthetic-one")
                self.assertEqual(second.mapping[0]["to"], ["synthetic-new"])

                self.reopen(reviewer)
                self.submit(
                    reviewer,
                    "cs_dictionary_review",
                    form=self.review_form(
                        reviewer, decision="RETIRE", note="سحب الإصدار بعد المقارنة الاصطناعية"
                    ),
                )
                self.submit(editor, "cs_shadow_read", code=409)
                self.assertNotIn("المُعاملاتِ", editor.locator("body").inner_text())
                self.reopen(editor)
                self.assertEqual(editor.locator("#shadow-history").count(), 0)
                self.assertEqual(
                    editor.locator('.dictionary-version[data-number="1"]').get_attribute(
                        "data-state"
                    ),
                    "RETIRE",
                )
                self.capture(editor, "retirement-removes-current-use")
                self.submit(editor, "cs_open")
                self.authority.denied.add("DICTIONARY_READ")
                self.submit(editor, "cs_dictionary_open", code=409)
                self.assertNotIn("قاموس بشري اصطناعي", editor.locator("body").inner_text())
                self.assertEqual(
                    self.sync(lambda: CaseSource.objects.get().original_question), self.question
                )
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before)
                self.assertEqual(self.sync(lambda: ShadowComparison.objects.count()), 1)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "protected_browser": True,
                            "sandbox": True,
                            "widths": [320, 1280],
                            "native_dictionary_creation": True,
                            "stable_lineage_mapping": True,
                            "actual_preview_baseline_total": 0,
                            "actual_preview_candidate_total": 2,
                            "self_review_denied": True,
                            "independent_reviewer": "other",
                            "actual_dictionary_result_count": 2,
                            "exact_original_response_bytes": True,
                            "literal_and_baseline_unchanged": True,
                            "actual_shadow_baseline_total": observed.baseline["total"],
                            "actual_shadow_candidate_total": observed.candidate["total"],
                            "actual_comparison_digest": observed.digest,
                            "current_source_pins": observed.source_pin,
                            "baseline_retained": True,
                            "promotion_performed": False,
                            "retired_dictionary_comparison_denied": True,
                            "current_reader_revocation_denied": True,
                            "canonical_case_history_unchanged": True,
                            "external_requests": 0,
                            "page_errors": 0,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
            except Exception as exc:
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "ERROR",
                            "error_type": type(exc).__name__,
                            "protected_browser": True,
                            "sandbox": True,
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
                raise
            finally:
                for context, name in zip(contexts, ("editor", "reviewer")):
                    context.tracing.stop(path=str(OUT / f"{name}-trace.zip"))
                    context.close()
                browser.close()
