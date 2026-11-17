"""Focused real-PostgreSQL requester journeys; all inputs are synthetic."""
import re
import time
from datetime import timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services
from apps.casework.models import Case, CaseEvidence
from apps.casework_web.requester_workspace import COOKIE, TTL, URL
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

WORKSPACE_SETTINGS = {
    **WEB_SETTINGS, "ROOT_URLCONF": "apps.casework_web.requester_workspace_urls",
}


@override_settings(**WORKSPACE_SETTINGS)
class RequesterWorkspaceTests(TransactionTestCase):
    def setUp(self):
        self.client = self.browser()
        self.directory = Directory()

    def browser(self):
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def intake(self, client=None, question="  سؤال اصطناعي محفوظ\nبلفظه الأصلي.  "):
        client = client or self.client
        form = client.get("/casework/")
        fields = {"question": question, "request_id": hidden(form, "request_id"),
                  "confirmation": hidden(form, "confirmation")}
        receipt = post(client, "/casework/", fields, form)
        self.assertEqual(receipt.status_code, 200)
        case = Case.objects.get(idempotency_key=fields["request_id"])
        token = re.search(r'id="issued-token">([^<]+)', receipt.content.decode()).group(1)
        return case, token, receipt, fields, form

    def unlock(self, token, client=None):
        client = client or self.client
        page = client.get(URL)
        return post(client, URL, {"action": "unlock", "token": token}, page)

    def followup(self, page, text="تعقيب اصطناعي", client=None):
        return post(client or self.client, URL, {
            "action": "followup", "revision": hidden(page, "revision"),
            "form_proof": hidden(page, "form_proof"), "text": text,
        }, page)

    def common(self, case):
        self.directory.grant(case.public_ref)
        return {"case_id": str(case.pk), "subject_id": self.directory.current.subject_id,
                "provider": self.directory, "synthetic_fixtures_only": True}

    def assertPrivate(self, response):
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("noindex", response["X-Robots-Tag"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_receipt_to_workspace_clarification_followup_and_staff_projection(self):
        case, token, receipt, fields, form = self.intake()
        self.assertContains(receipt, "متابعة هذا السؤال")
        cookie = receipt.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], URL)
        self.assertEqual(cookie["max-age"], TTL)
        page = self.client.get(URL)
        self.assertContains(page, case.public_ref)
        self.assertNotContains(page, token)
        self.assertNotContains(page, case.source.original_question)
        common = self.common(case)
        services.request_clarification(**common, text="تفصيل اصطناعي مطلوب؟",
                                       expected_revision=1, expected_evidence_version=1)
        page = self.client.get(URL)
        self.assertContains(page, "تفصيل اصطناعي مطلوب؟")
        self.assertNotContains(page, "الجواب متاح")
        reply = "  توضيح اصطناعي\nمع الحفاظ على الفراغات.  "
        response = self.followup(page, reply)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], URL)
        self.assertPrivate(response)
        page = self.client.get(URL)
        self.assertContains(page, 'id="followup-count">1<')
        self.assertContains(page, "قيد المراجعة")
        self.assertNotContains(page, "تفصيل اصطناعي مطلوب؟")
        self.assertEqual(services.read_case(**common)["followups"][0]["text"], reply)
        self.assertEqual(case.source.original_question, fields["question"])
        # Receipt retry and refreshing the status do not create a second source/evidence.
        replay = post(self.client, "/casework/", fields, form)
        self.assertEqual(replay.status_code, 200)
        self.assertNotContains(replay, token)
        self.client.get(URL)
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.count(), 2)
        drafted = services.save_answer(**common, text="مسودة بشرية اصطناعية خاصة",
                                       expected_revision=3, expected_evidence_version=2)
        services.record_decision(**common, answer_id=drafted["answers"][0]["id"],
                                 action="APPROVE", expected_revision=4, expected_evidence_version=2)
        approved = self.client.get(URL)
        self.assertContains(approved, "اكتملت مراجعة الجواب")
        for private_value in ("مسودة بشرية اصطناعية خاصة", token, "الجواب متاح", "ANSWERED"):
            self.assertNotContains(approved, private_value)

    def test_stale_followup_keeps_text_and_requires_explicit_resubmit(self):
        case, token, *_ = self.intake()
        old_page = self.client.get(URL)
        services.add_followup(token=token, text="حقائق وصلت في نافذة أخرى", expected_revision=1,
                              synthetic_fixtures_only=True)
        response = self.followup(old_page, "نص لم يُرسل بعد <script>ليس شيفرة</script>")
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "لم يُحفظ التعقيب", status_code=409)
        self.assertContains(response, "&lt;script&gt;ليس شيفرة&lt;/script&gt;", status_code=409)
        self.assertEqual(case.evidence.count(), 2)
        self.assertEqual(self.followup(response, "نص بعد المراجعة").status_code, 303)
        self.assertEqual(case.evidence.count(), 3)
        self.assertEqual(self.followup(response, "نص بعد المراجعة").status_code, 409)
        self.assertEqual(case.evidence.count(), 3)

    def test_case_switch_cannot_redirect_stale_tab_followup_to_another_case(self):
        alpha, alpha_token, *_ = self.intake()
        old_page = self.client.get(URL)
        other = self.browser()
        beta, beta_token, *_ = self.intake(other, "سؤال اصطناعي مستقل")
        self.assertEqual(self.unlock(beta_token).status_code, 303)
        response = self.followup(old_page, "PRIVATE ALPHA FOLLOWUP")
        self.assertEqual(response.status_code, 409)
        for hidden_value in (alpha.public_ref, alpha_token, beta_token, "PRIVATE ALPHA FOLLOWUP"):
            self.assertNotContains(response, hidden_value, status_code=409)
        self.assertEqual(alpha.evidence.count(), 1)
        self.assertEqual(beta.evidence.count(), 1)
        # Original client capabilities do not authorize internal staff routes.
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)

    def test_token_rotation_revocation_and_expiry_rechecked_for_every_request(self):
        case, token, *_ = self.intake()
        page = self.client.get(URL)
        common = self.common(case)
        replacement = services.rotate_access(**common, requester_id=case.requester_id)["token"]
        rejected = self.followup(page)
        self.assertEqual(rejected.status_code, 404)
        self.assertNotContains(rejected, case.public_ref, status_code=404)
        self.assertEqual(self.unlock(token).status_code, 404)
        self.assertEqual(self.unlock(replacement).status_code, 303)
        self.assertContains(self.client.get(URL), case.public_ref)
        services.revoke_access(**common, requester_id=case.requester_id)
        self.assertNotContains(self.client.get(URL), case.public_ref)
        newest = services.rotate_access(**common, requester_id=case.requester_id)["token"]
        self.assertEqual(self.unlock(newest).status_code, 303)
        with patch("apps.casework.services.timezone.now",
                   return_value=timezone.now() + timedelta(days=8)):
            self.assertNotContains(self.client.get(URL), case.public_ref)
        self.assertEqual(case.evidence.count(), 1)

    def test_cookie_tampering_browser_binding_expiry_and_leave(self):
        case, token, *_ = self.intake()
        cookie = self.client.cookies[COOKIE].value
        other = self.browser()
        other.get(URL)
        other.cookies[COOKIE] = cookie
        self.assertNotContains(other.get(URL), case.public_ref)
        self.client.cookies[COOKIE] = cookie + "tampered"
        self.assertNotContains(self.client.get(URL), case.public_ref)
        self.assertEqual(self.unlock(token).status_code, 303)
        with patch("django.core.signing.time.time", return_value=time.time() + TTL + 2):
            self.assertNotContains(self.client.get(URL), case.public_ref)
        self.assertEqual(self.unlock(token).status_code, 303)
        cookie = self.client.cookies[COOKIE].value
        page = self.client.get(URL)
        response = post(self.client, URL, {"action": "leave"}, page)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
        self.client.cookies[COOKIE] = cookie
        self.assertNotContains(self.client.get(URL), case.public_ref)
        # Closing this browser is not a claim to revoke the recovery capability.
        self.assertEqual(self.unlock(token).status_code, 303)

    def test_csrf_exact_forms_query_rejection_and_read_only_get(self):
        case, token, *_ = self.intake()
        page = self.client.get(URL)
        before = list(case.events.values_list("sequence", "action"))
        for _ in range(2):
            self.assertPrivate(self.client.get(URL))
        self.assertEqual(list(case.events.values_list("sequence", "action")), before)
        self.assertEqual(self.client.get(URL + "?token=synthetic").status_code, 400)
        self.assertEqual(self.client.post(URL, {"action": "leave"}).status_code, 403)
        self.assertEqual(post(self.client, URL, {"action": "unlock", "token": token,
                                                "case_ref": case.public_ref}, page).status_code, 400)
        self.assertEqual(self.client.get(URL, REMOTE_ADDR="192.0.2.9").status_code, 403)
        self.assertEqual(self.client.get(URL, HTTP_HOST="attacker.example").status_code, 400)
        head = self.client.head(URL)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=False):
            self.assertEqual(self.client.get(URL).status_code, 503)

    def test_reference_and_bad_tokens_share_error_without_leaking_current_case(self):
        case, token, *_ = self.intake()
        outputs = []
        for bad in (case.public_ref, "invalid", "rt_" + "x" * 43):
            response = self.unlock(bad)
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, case.public_ref, status_code=404)
            self.assertNotContains(response, token, status_code=404)
            outputs.append(response.context["message"])
            self.assertNotContains(self.client.get(URL), case.public_ref)
        self.assertEqual(len(set(outputs)), 1)

    def test_validation_preserves_escaped_input_and_no_success_on_store_failure(self):
        page = self.client.get("/casework/")
        fields = {"question": " " * 4, "request_id": hidden(page, "request_id"),
                  "confirmation": hidden(page, "confirmation")}
        response = post(self.client, "/casework/", fields, page)
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'id="intake-result"', status_code=400)
        self.assertEqual(Case.objects.count(), 0)
        with patch("apps.casework_web.requester_intake.services.intake_case", side_effect=DatabaseError):
            response = post(self.client, "/casework/", {**fields, "question": "سؤال اصطناعي"}, page)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(COOKIE, response.cookies)
        case, _, *_ = self.intake()
        page = self.client.get(URL)
        self.assertEqual(self.followup(page, " \n ").status_code, 400)
        self.assertEqual(self.followup(page, "x" * 16001).status_code, 400)
        self.assertEqual(case.evidence.count(), 1)

    def test_revocation_during_followup_does_not_return_stale_clarification(self):
        case, _, *_ = self.intake()
        common = self.common(case)
        services.request_clarification(**common, text="استيضاح خاص اصطناعي",
                                       expected_revision=1, expected_evidence_version=1)
        page = self.client.get(URL)
        original = services.add_followup

        def revoke_then_write(**kwargs):
            services.revoke_access(**common, requester_id=case.requester_id)
            return original(**kwargs)

        with patch("apps.casework_web.requester_workspace.services.add_followup", side_effect=revoke_then_write):
            response = self.followup(page)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "استيضاح خاص اصطناعي", status_code=404)
        self.assertNotContains(response, case.public_ref, status_code=404)
        self.assertEqual(case.evidence.count(), 1)
