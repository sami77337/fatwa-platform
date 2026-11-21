"""Protected native two-person judgments, real runs, independent decisions and staleness."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings
from django.utils.html import escape

from apps.canonical_search.browser_tests import CanonicalSearchBrowserTests
from apps.canonical_search.governance_test_support import CREDENTIALS
from apps.canonical_search.models import ShadowComparison
from apps.casework.models import CaseEvent, CaseSource

from .benchmark_test_support import FEATURES, BenchmarkFixture
from .models import (
    CanonicalBenchmarkDecision,
    CanonicalBenchmarkRun,
    EvaluationDecision,
    EvaluationRevision,
)
from .test_benchmark_http import query_fields

OUT = Path(".local/qa/functional-continuation/search-benchmark-browser")


@override_settings(**FEATURES)
class CanonicalBenchmarkBrowserTests(BenchmarkFixture, LiveServerTestCase):
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

    def reopen(self, page, *, code=200):
        page.goto(self.live_server_url + "/casework/staff/")
        self.submit(page, "open")
        self.submit(page, "cs_open")
        self.submit(page, "cs_benchmark_open", code=code)
        if code == 200:
            self.assertEqual(page.locator("#canonical-benchmark").count(), 1)

    def propose_native(self, page, *, newer=False):
        page.locator("#benchmark-proposal > summary").click()
        fields = query_fields()
        if newer:
            fields["q_0_expected"] = "1، 2"
            fields["q_0_rationale"] = "تعديل بشري صريح للحكم الاصطناعي؛ يلزمه قرار مستقل جديد."
        form = page.locator("#benchmark-propose-form")
        for name, value in fields.items():
            form.locator(f'[name="{name}"]').fill(value)
        form.locator('[name="note"]').fill("أحكام اصطناعية كتبها المستخدم على المصادر الحالية.")
        self.submit(page, "cs_benchmark_propose", form=form)

    def judge_native(self, page, *, code=200):
        form = page.locator("#benchmark-judge-form")
        for index in range(3):
            form.locator(f'[name="r_{index}_verdict"]').select_option("AGREE")
            form.locator(f'[name="r_{index}_note"]').fill(
                "راجعت هذا التوقع الاصطناعي مع المواضع الأصلية."
            )
        form.locator('[name="note"]').fill("أوافق على الأحكام لهذه المجموعة الاصطناعية فقط.")
        form.locator('[name="confirm"]').check()
        self.submit(page, "cs_benchmark_judge", form=form, code=code)

    def review_native(self, page, *, code=200):
        form = page.locator("#benchmark-result-review-form")
        form.locator('[name="decision"]').select_option("ACCEPT")
        form.locator('[name="note"]').fill(
            "راجعت المقاييس والنتائج الفعلية بلا تغيير إعداد البحث العام."
        )
        form.locator('[name="confirm"]').check()
        self.submit(page, "cs_benchmark_review", form=form, code=code)

    def test_native_authored_judgments_actual_metrics_independent_decisions_and_current_denials(
        self,
    ):
        from playwright.sync_api import sync_playwright

        # Existing dictionary workflow has its own native browser journey. Here
        # only its service-created reviewed candidate is a starting fixture;
        # every judgment, benchmark run and run decision below is a native form.
        self.approved()
        before = CaseEvent.objects.count()
        OUT.mkdir(parents=True, exist_ok=True)
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
                original = self.submit(editor, "cs_source")
                self.assertIn(str(escape(self.question)).encode(), original.body())
                self.assertEqual(
                    editor.locator("#canonical-source-text").text_content(),
                    self.question.replace("\r\n", "\n"),
                )
                self.reopen(editor)
                self.propose_native(editor)
                self.capture(editor, "pending-authored-judgments")
                self.judge_native(editor, code=409)
                self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 0)
                self.enter(reviewer, "other")
                self.judge_native(reviewer)
                self.assertIn(
                    "أحكام مراجعَة باستقلال",
                    reviewer.locator("#benchmark-suite-status").inner_text(),
                )
                self.capture(reviewer, "independently-reviewed-judgments")
                self.reopen(editor)
                self.form(editor, "cs_benchmark_run").locator('[name="note"]').fill(
                    "مقارنة فعلية لثلاثة استعلامات بأحكام محددة سلفًا."
                )
                self.submit(editor, "cs_benchmark_run")
                self.assertEqual(editor.locator(".benchmark-query-result").count(), 3)
                self.assertIn("0,750", editor.locator("#benchmark-summary").inner_text())
                self.assertIn(
                    "التكلفة المالية لقاعدة البيانات غير مقاسة",
                    editor.locator("#benchmark-result").inner_text(),
                )
                self.capture(editor, "actual-query-results-and-metrics")
                self.review_native(editor, code=409)
                self.assertEqual(self.sync(lambda: CanonicalBenchmarkDecision.objects.count()), 0)
                self.reopen(reviewer)
                self.submit(reviewer, "cs_benchmark_read")
                self.review_native(reviewer)
                self.assertIn(
                    "قبل المراجع المستقل", reviewer.locator("#benchmark-run-review").inner_text()
                )
                self.capture(reviewer, "independent-run-decision")
                observed = self.sync(lambda: CanonicalBenchmarkRun.objects.get())
                self.assertEqual(observed.metrics["summary"]["baseline"]["precision_at_5"], 0.5)
                self.assertEqual(observed.metrics["summary"]["candidate"]["precision_at_5"], 0.75)
                self.assertEqual(observed.metrics["summary"]["baseline"]["recall_at_5"], 0.25)
                self.assertEqual(observed.metrics["summary"]["candidate"]["recall_at_5"], 0.75)
                self.assertEqual(self.sync(lambda: ShadowComparison.objects.count()), 3)
                self.reopen(editor)
                self.propose_native(editor, newer=True)
                self.assertEqual(self.sync(lambda: EvaluationRevision.objects.count()), 2)
                self.assertEqual(self.sync(lambda: EvaluationDecision.objects.count()), 1)
                self.assertIn(
                    "بانتظار مراجعة مستقلة", editor.locator("#benchmark-suite-status").inner_text()
                )
                self.assertEqual(editor.locator(".benchmark-run-form").count(), 0)
                self.submit(reviewer, "cs_benchmark_read", code=409)
                self.assertEqual(reviewer.locator("#benchmark-result").count(), 0)
                self.capture(editor, "new-judgments-do-not-inherit-review")
                self.benchmark_authority.denied.add("READ")
                self.reopen(editor, code=409)
                self.assertEqual(editor.locator("#benchmark-corpus").count(), 0)
                self.assertEqual(self.sync(lambda: CaseEvent.objects.count()), before)
                self.assertEqual(
                    self.sync(lambda: CaseSource.objects.get().original_question), self.question
                )
                self.assertEqual(self.sync(lambda: CanonicalBenchmarkRun.objects.count()), 1)
                self.assertEqual(self.sync(lambda: CanonicalBenchmarkDecision.objects.count()), 1)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "protected_browser": True,
                            "sandbox": True,
                            "widths": [320, 1280],
                            "native_authored_judgments": True,
                            "self_judgment_review_denied": True,
                            "independent_judgment_reviewer": "other",
                            "actual_query_pairs": 3,
                            "actual_metrics": observed.metrics,
                            "actual_workload": observed.workload,
                            "run_digest": observed.digest,
                            "source_pin": observed.source_pin,
                            "code_pin": observed.code_pin,
                            "self_run_review_denied": True,
                            "independent_run_reviewer": "other",
                            "stale_judgments_read_denied": True,
                            "new_judgments_review_pending": True,
                            "current_reader_revocation_denied": True,
                            "exact_original_response_bytes": True,
                            "canonical_case_history_unchanged": True,
                            "synthetic_only": True,
                            "real_gold_benchmark_claimed": False,
                            "promotion_performed": False,
                            "page_errors": 0,
                            "external_requests": 0,
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
                for context, name in zip(contexts, ("editor", "reviewer"), strict=True):
                    context.tracing.stop(path=str(OUT / f"{name}-trace.zip"))
                    context.close()
                browser.close()
