"""Native bounded forms, CSRF, exact browser state and response-time revocation."""

from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.canonical_search.governance_test_support import CREDENTIALS, TERM
from apps.canonical_search.test_governance_http import form_state
from apps.casework.models import CaseEvent
from tests.casework.test_http import post

from . import benchmark_views
from .benchmark_test_support import FEATURES, BenchmarkFixture
from .models import (
    CanonicalBenchmarkDecision,
    CanonicalBenchmarkRun,
    EvaluationDecision,
    EvaluationRevision,
)


def query_fields():
    fields = {key: "" for key in benchmark_views.QUERY_FIELDS}
    fields.update(
        q_0_query=TERM,
        q_0_expected="1",
        q_0_rationale="حكم اصطناعي: السؤال ذو صلة، والجواب مشتت لهذا الاستعلام.",
        q_1_query="الزكاة",
        q_1_expected="1، 2",
        q_1_rationale="توقع اصطناعي يشمل النصين، وقد يغيب الجواب عن المطابقة اللفظية.",
        q_2_query="غيرموجوداصطناعيا",
        q_2_expected="",
        q_2_rationale="استعلام اصطناعي سلبي لا مقابل له.",
    )
    return fields


def review_fields():
    fields = {key: "" for key in benchmark_views.REVIEW_FIELDS}
    for i in range(3):
        fields[f"r_{i}_verdict"] = "AGREE"
        fields[f"r_{i}_note"] = "راجعت التوقع الاصطناعي باستقلال عن مؤلفه."
    return fields


@override_settings(**FEATURES)
class CanonicalBenchmarkHTTPTests(BenchmarkFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client, "/casework/staff/login/", {"credential": CREDENTIALS[subject]}, page
        )
        self.assertEqual(response.status_code, 303, response.content)
        return client, client.get("/casework/staff/")

    def submit(self, client, page, action, **fields):
        return post(
            client,
            "/casework/staff/",
            {"action": action, "case_ref": self.receipt["public_ref"], **fields},
            page,
        )

    def open(self, subject="editor"):
        client, page = self.login(subject)
        page = self.submit(client, page, "cs_benchmark_open")
        self.assertEqual(page.status_code, 200, page.content)
        return client, page

    def propose_page(self, client, page, **changes):
        return self.submit(
            client,
            page,
            "cs_benchmark_propose",
            **{
                "state": form_state(page, "cs_benchmark_propose"),
                "note": "مجموعة أحكام اصطناعية مع مصدر حالي.",
                **query_fields(),
                **changes,
            },
        )

    def judge_page(self, client, page, **changes):
        return self.submit(
            client,
            page,
            "cs_benchmark_judge",
            **{
                "state": form_state(page, "cs_benchmark_judge"),
                "decision": "APPROVE",
                "note": "قرار مستقل للأحكام الاصطناعية.",
                "confirm": "yes",
                **review_fields(),
                **changes,
            },
        )

    def test_native_judgments_two_independent_decisions_and_actual_metric_report(self):
        self.approved()
        events = CaseEvent.objects.count()
        client, page = self.open()
        self.assertContains(page, "لم يُنشأ إصدار أحكام")
        page = self.propose_page(client, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "بانتظار مراجعة مستقلة")
        self.assertEqual(self.judge_page(client, page).status_code, 409)
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        reviewer, other = self.open("other")
        other = self.judge_page(reviewer, other)
        self.assertEqual(other.status_code, 200, other.content)
        self.assertContains(other, "أحكام مراجعَة باستقلال")
        page = self.submit(client, page, "cs_benchmark_open")
        page = self.submit(
            client,
            page,
            "cs_benchmark_run",
            state=form_state(page, "cs_benchmark_run"),
            note="تنفيذ فعلي مقصود للتقييم الاصطناعي.",
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="benchmark-summary"')
        self.assertContains(page, "0,750")
        self.assertContains(page, "التكلفة المالية لقاعدة البيانات غير مقاسة")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 1)
        self_decision = self.submit(
            client,
            page,
            "cs_benchmark_review",
            state=form_state(page, "cs_benchmark_review"),
            decision="ACCEPT",
            note="قرار ذاتي مرفوض.",
            confirm="yes",
        )
        self.assertEqual(self_decision.status_code, 409)
        self.assertEqual(CanonicalBenchmarkDecision.objects.count(), 0)
        other = self.submit(reviewer, other, "cs_benchmark_open")
        other = self.submit(
            reviewer, other, "cs_benchmark_read", state=form_state(other, "cs_benchmark_read")
        )
        other = self.submit(
            reviewer,
            other,
            "cs_benchmark_review",
            state=form_state(other, "cs_benchmark_review"),
            decision="ACCEPT",
            note="قرأت القياسات والفروق والتزمت بنطاق الأحكام الاصطناعية.",
            confirm="yes",
        )
        self.assertEqual(other.status_code, 200, other.content)
        self.assertContains(other, "قبل المراجع المستقل هذه التجربة المحددة")
        self.assertEqual(CanonicalBenchmarkDecision.objects.count(), 1)
        self.assertEqual(CaseEvent.objects.count(), events)

    def test_csrf_default_off_strict_fields_and_browser_bound_source_state(self):
        client, page = self.open()
        self.assertEqual(
            client.post(
                "/casework/staff/",
                {"action": "cs_benchmark_open", "case_ref": self.receipt["public_ref"]},
            ).status_code,
            403,
        )
        other_client, other_page = self.open("other")
        crossed = self.propose_page(
            other_client, other_page, state=form_state(page, "cs_benchmark_propose")
        )
        self.assertEqual(crossed.status_code, 400)
        extra = self.propose_page(client, page, accepted=True)
        self.assertEqual(extra.status_code, 400)
        duplicate = self.propose_page(client, page, q_0_expected="1,1")
        self.assertEqual(duplicate.status_code, 409)
        with override_settings(FATWA_CANONICAL_BENCHMARK_ENABLED=False):
            self.assertEqual(self.submit(client, page, "cs_benchmark_open").status_code, 409)
        self.assertEqual(EvaluationRevision.objects.count(), 0)

    def test_stale_corpus_form_and_post_render_revocation_roll_back_authored_revision(self):
        client, page = self.open()
        render = benchmark_views.render

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.benchmark_authority.denied.add("READ")
            return response

        with patch.object(benchmark_views, "render", side_effect=revoke):
            response = self.propose_page(client, page)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(EvaluationRevision.objects.count(), 0)
        self.benchmark_authority.denied.clear()
        self.answer("نص حالي مختلف يغير الفهرس القديم.")
        self.build()
        self.assertEqual(self.propose_page(client, page).status_code, 409)
        self.assertEqual(EvaluationRevision.objects.count(), 0)

    def test_run_and_all_query_receipts_roll_back_when_current_reader_revoked_at_render(self):
        self.ready()
        client, page = self.open()
        render = benchmark_views.render

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.benchmark_authority.denied.add("READ")
            return response

        from apps.canonical_search.models import ShadowComparison

        with patch.object(benchmark_views, "render", side_effect=revoke):
            response = self.submit(
                client,
                page,
                "cs_benchmark_run",
                state=form_state(page, "cs_benchmark_run"),
                note="تجربة تتغير صلاحية قراءة نتيجتها أثناء الاستجابة.",
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CanonicalBenchmarkRun.objects.count(), 0)
        self.assertEqual(ShadowComparison.objects.count(), 0)
