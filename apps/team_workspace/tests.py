"""Focused PostgreSQL/HTTP regressions using synthetic fixtures only."""

from dataclasses import replace
from html import unescape
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import override_settings

from apps.casework import services
from apps.casework.models import CaseEvent
from tests.casework import test_http as contracts
from tests.casework.test_http import hidden, post


@override_settings(ROOT_URLCONF="apps.team_workspace.urls")
class TeamWorkspaceTests(contracts.CaseworkHTTPTests):
    """Also run the existing HTTP contracts against the optional replacement screen."""

    def mutation(self, page, action, **extra):
        selected = page.context["selected"]
        return post(self.client, "/casework/staff/", {
            "action": action, "case_ref": selected["public_ref"],
            "revision": str(selected["revision"]),
            "evidence_version": str(selected["evidence_version"]), **extra,
        }, page)

    def setup_case(self):
        case, token, _, _, _ = self.intake()
        self.directory.grant(case.public_ref)
        return case, token, self.open_case(case, self.login())

    def test_auth_epoch_change_between_cookie_check_and_core_call_rejects_write(self):
        from apps.casework_web.access import current_staff

        case, _, page = self.setup_case()

        def revoke_after_check(*args, **kwargs):
            identity = current_staff(*args, **kwargs)
            self.directory.current = replace(self.directory.current, auth_epoch="epoch-revoked")
            return identity

        with patch("apps.team_workspace.views.current_staff", side_effect=revoke_after_check):
            response = self.mutation(page, "draft", text="must not be saved")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(case.answers.count(), 0)
        self.assertEqual(case.events.count(), 1)

    def test_scoped_queue_search_filters_counts_and_empty_state(self):
        alpha, _, _, _, _ = self.intake("PRIVATE ALPHA")
        beta, _, _, _, _ = self.intake("PRIVATE BETA")
        other, _, _, _, _ = self.intake("OUT OF SCOPE")
        self.directory.grant(alpha.public_ref, beta.public_ref)
        page = self.open_case(alpha, self.login())
        page = self.mutation(page, "clarify", text="تفصيل اصطناعي")
        before = list(CaseEvent.objects.values_list("id", flat=True))
        response = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "waiting", "query": "", "sort": "newest",
        }, page)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, alpha.public_ref)
        self.assertNotContains(response, beta.public_ref)
        self.assertNotContains(response, other.public_ref)
        self.assertNotContains(response, "PRIVATE ALPHA")
        self.assertEqual({item["key"]: item["count"] for item in response.context["filters"]},
                         {"all": 2, "draft": 1, "waiting": 1, "review": 0,
                          "returned": 0, "approved": 0})
        response = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "all", "query": other.public_ref, "sort": "newest",
        }, response)
        self.assertContains(response, 'id="empty-queue"')
        self.assertEqual(response.context["rows"], [])
        self.assertEqual(list(CaseEvent.objects.values_list("id", flat=True)), before)

    def test_inbox_counts_remain_global_when_search_narrows_results(self):
        waiting, _, _, _, _ = self.intake("سؤال اصطناعي ينتظر استيضاحًا")
        draft_case, _, _, _, _ = self.intake("سؤال اصطناعي عن أحكام البيع")
        approved_case, _, _, _, _ = self.intake("سؤال اصطناعي عن الصيام")
        self.directory.grant(waiting.public_ref, draft_case.public_ref, approved_case.public_ref)
        page = self.open_case(waiting, self.login())
        page = self.mutation(page, "clarify", text="يلزم استيضاح الوقائع")
        draft_page = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": draft_case.public_ref,
        }, page)
        draft_page = self.mutation(draft_page, "draft", text="مسودة اصطناعية للمراجعة")
        approved_page = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": approved_case.public_ref,
        }, draft_page)
        approved_page = self.mutation(approved_page, "draft", text="جواب اصطناعي")
        approved_page = self.mutation(
            approved_page, "approve", answer_id=hidden(approved_page, "answer_id"), note=""
        )
        before = list(CaseEvent.objects.values_list("id", flat=True))
        filtered = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "waiting", "query": waiting.public_ref, "sort": "newest",
        }, approved_page)
        self.assertEqual(filtered.status_code, 200, filtered.content)
        self.assertEqual(filtered.context["total"], 3)
        self.assertEqual(filtered.context["matched_total"], 1)
        self.assertEqual(filtered.context["visible_total"], 1)
        counts = {item["key"]: item["count"] for item in filtered.context["filters"]}
        self.assertEqual(counts, {
            "all": 3, "draft": 0, "waiting": 1, "review": 1,
            "returned": 0, "approved": 1,
        })
        self.assertEqual(list(CaseEvent.objects.values_list("id", flat=True)), before)
        self.assertContains(filtered, waiting.public_ref)
        self.assertNotContains(filtered, draft_case.public_ref)
        self.assertNotContains(filtered, approved_case.public_ref)

    def test_previously_rendered_filter_without_sort_keeps_newest_scoped_order(self):
        older, _, _, _, _ = self.intake("PRIVATE SHARED OLDER")
        newer, _, _, _, _ = self.intake("PRIVATE SHARED NEWER")
        hidden_case, _, _, _, _ = self.intake("PRIVATE SHARED OUT OF SCOPE")
        self.directory.grant(older.public_ref, newer.public_ref)
        page = self.open_case(older, self.login())
        before = list(CaseEvent.objects.values_list("id", flat=True))
        response = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "draft", "query": "shared",
        }, page)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.context["sort"], "newest")
        self.assertEqual(
            [row["public_ref"] for row in response.context["rows"]],
            [newer.public_ref, older.public_ref],
        )
        self.assertEqual(response.context["total"], 2)
        self.assertEqual(response.context["visible_total"], 2)
        self.assertNotContains(response, hidden_case.public_ref)
        self.assertNotContains(response, "PRIVATE SHARED")
        self.assertEqual(list(CaseEvent.objects.values_list("id", flat=True)), before)

    def test_priority_queue_sort_orders_actionable_work_before_waiting_and_approved(self):
        waiting, _, _, _, _ = self.intake("سؤال ينتظر السائل")
        returned, _, _, _, _ = self.intake("سؤال معاد للتعديل")
        review, _, _, _, _ = self.intake("سؤال جاهز للمراجعة")
        approved, _, _, _, _ = self.intake("سؤال معتمد")
        self.directory.grant(
            waiting.public_ref, returned.public_ref, review.public_ref, approved.public_ref
        )
        page = self.open_case(returned, self.login())
        page = self.mutation(page, "draft", text="مسودة أولى")
        page = self.mutation(page, "return", answer_id=hidden(page, "answer_id"), note="تعديل مطلوب")
        page = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": review.public_ref,
        }, page)
        page = self.mutation(page, "draft", text="جواب ينتظر المراجعة")
        page = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": approved.public_ref,
        }, page)
        page = self.mutation(page, "draft", text="جواب معتمد")
        page = self.mutation(page, "approve", answer_id=hidden(page, "answer_id"), note="")
        page = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": waiting.public_ref,
        }, page)
        page = self.mutation(page, "clarify", text="نحتاج معلومة")
        priority = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "all", "query": "", "sort": "priority",
        }, page)
        self.assertEqual(priority.status_code, 200, priority.content)
        self.assertEqual(
            [row["category"] for row in priority.context["rows"]],
            ["returned", "review", "waiting", "approved"],
        )
        oldest = post(self.client, "/casework/staff/", {
            "action": "filter", "state": "all", "query": "", "sort": "oldest",
        }, priority)
        self.assertEqual(oldest.status_code, 200, oldest.content)
        self.assertEqual(oldest.context["rows"][0]["public_ref"], waiting.public_ref)
        self.assertEqual(oldest.context["sort"], "oldest")

    def test_edit_return_reason_reopen_new_version_and_approval(self):
        case, _, page = self.setup_case()
        original = "  مسودة <اصطناعية> & بشرية.  "
        page = self.mutation(page, "draft", text=original)
        self.assertEqual(page.context["selected"]["latest_answer"]["text"], original)
        self.assertIn(original, unescape(page.content.decode()))
        self.assertContains(page, 'value="approve"', count=1)
        answer_id = hidden(page, "answer_id")
        page = self.mutation(page, "return", answer_id=answer_id, note="وضّح صياغة المثال")
        self.assertEqual(page.status_code, 200)
        page = self.open_case(case, self.client.get("/casework/staff/"))
        self.assertContains(page, "وضّح صياغة المثال")
        self.assertNotContains(page, 'value="approve"')
        page = self.mutation(page, "draft", text="صياغة منقحة اصطناعية")
        self.assertEqual(case.answers.count(), 2)
        self.assertEqual(case.answers.get(revision=1).text, original)
        page = self.mutation(page, "approve", answer_id=hidden(page, "answer_id"), note="تمت المراجعة")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "تمت المراجعة")
        self.assertEqual(page.context["selected"]["category"], "approved")
        self.assertNotContains(page, 'value="approve"')
        page = self.mutation(page, "draft", text="إصدار ثالث جديد")
        case.refresh_from_db()
        self.assertIsNone(case.approved_answer_id)
        self.assertEqual(case.answer_revision, 3)
        self.assertContains(page, 'value="approve"', count=1)

    def test_stale_text_preserved_separately_and_old_decision_rejected(self):
        case, token, page = self.setup_case()
        page = self.mutation(page, "draft", text="مسودة محفوظة")
        stale_page = page
        old_answer = hidden(page, "answer_id")
        services.add_followup(token=token, text="وقائع جديدة", expected_revision=2,
                              synthetic_fixtures_only=True)
        attempted = "  <script>alert('synthetic')</script> نص غير محفوظ  "
        response = self.mutation(stale_page, "draft", text=attempted)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["attempted_text"], attempted)
        self.assertEqual(response.context["selected"]["latest_answer"]["text"], "مسودة محفوظة")
        self.assertNotContains(response, "<script>", status_code=409)
        self.assertContains(response, 'id="stale-answer"', status_code=409)
        self.assertNotContains(response, 'value="approve"', status_code=409)
        self.assertEqual(case.answers.count(), 1)
        response = self.mutation(stale_page, "approve", answer_id=old_answer, note="")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(case.decisions.count(), 0)

    def test_only_latest_answer_reviewable_and_decided_answer_cannot_be_replayed(self):
        case, _, page = self.setup_case()
        page = self.mutation(page, "draft", text="الإصدار الأول")
        old_answer = hidden(page, "answer_id")
        page = self.mutation(page, "draft", text="الإصدار الثاني")
        self.assertContains(page, 'value="approve"', count=1)
        self.assertNotContains(page, f'value="{old_answer}"')
        forged = self.mutation(page, "approve", answer_id=old_answer, note="")
        self.assertEqual(forged.status_code, 409)
        self.assertEqual(case.decisions.count(), 0)
        current = hidden(page, "answer_id")
        page = self.mutation(page, "return", answer_id=current, note="تعديل مطلوب")
        repeated = self.mutation(page, "approve", answer_id=current, note="")
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(case.decisions.count(), 1)

    def test_return_requires_reason_and_waiting_hides_approval(self):
        case, _, page = self.setup_case()
        page = self.mutation(page, "draft", text="مسودة")
        answer_id = hidden(page, "answer_id")
        refused = self.mutation(page, "return", answer_id=answer_id, note="   ")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(case.decisions.count(), 0)
        page = self.mutation(page, "clarify", text="ماذا تقصد؟")
        self.assertNotContains(page, 'value="approve"')
        self.assertNotContains(page, 'name="action" value="draft"')
        refused = self.mutation(page, "draft", text="محاولة تجاوز انتظار الاستيضاح")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(case.answers.count(), 1)
        case.refresh_from_db()
        self.assertEqual(case.stage, "NEEDS_CLARIFICATION")
        refused = self.mutation(page, "approve", answer_id=answer_id, note="")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(case.decisions.count(), 0)

    def test_workspace_filters_reject_forged_role_duplicates_and_missing_csrf(self):
        _, _, page = self.setup_case()
        for fields in (
            {"action": "filter", "state": "all", "query": "", "sort": "newest", "role": "MUFTI"},
            {"action": "filter", "state": "unknown", "query": "", "sort": "newest"},
            {"action": "filter", "state": "all", "query": "x" * 41, "sort": "newest"},
            {"action": "filter", "state": "all", "query": "", "sort": "unknown"},
            {"action": "filter", "state": "all", "query": "", "sort": ""},
            {"action": "filter", "state": "all", "query": "", "role": "MUFTI"},
        ):
            self.assertEqual(post(self.client, "/casework/staff/", fields, page).status_code, 400)
        duplicate = urlencode({"action": "filter", "state": "all", "query": "", "sort": "newest",
                               "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken")})
        for repeated in ("&state=review", "&sort=oldest"):
            response = self.client.post("/casework/staff/", duplicate + repeated,
                                        content_type="application/x-www-form-urlencoded")
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/casework/staff/", "action=filter&state=all&query=&sort=newest",
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 403)

    def test_role_revocation_blocks_read_and_does_not_echo_attempt(self):
        case, _, page = self.setup_case()
        self.directory.current = replace(self.directory.current, role="ORGANIZER")
        response = self.mutation(page, "draft", text="PRIVATE UNSAVED TEXT")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("PRIVATE UNSAVED TEXT", response.content.decode())
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.assertEqual(case.answers.count(), 0)

    def test_clarification_between_preflight_and_save_rejects_stale_write(self):
        case, _, page = self.setup_case()
        save_answer = services.save_answer

        def clarify_before_save(**kwargs):
            services.request_clarification(**{**kwargs, "text": "استيضاح وصل أثناء التحرير"})
            return save_answer(**kwargs)

        with patch("apps.team_workspace.views.services.save_answer", side_effect=clarify_before_save):
            response = self.mutation(page, "draft", text="مسودة سبقتها وقائع جديدة")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(case.answers.count(), 0)
        case.refresh_from_db()
        self.assertEqual(case.stage, "NEEDS_CLARIFICATION")
        self.assertContains(response, "استيضاح وصل أثناء التحرير", status_code=409)

    def test_open_and_head_are_read_only_and_recovery_requires_resolver(self):
        case, _, page = self.setup_case()
        before = list(case.events.values_list("id", flat=True))
        page = self.open_case(case, page)
        self.assertNotContains(page, 'value="rotate"')
        self.assertNotContains(page, 'value="revoke"')
        response = self.client.head("/casework/staff/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(list(case.events.values_list("id", flat=True)), before)
