"""Adversarial HTTP contracts for the synthetic website / requester / Mufti journey."""
import re
from dataclasses import replace
from datetime import timedelta
from html import unescape
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services
from apps.casework.models import Case, CaseEvent, CaseSource
from apps.casework_web.access import COOKIE
from apps.casework_web.models import ThrottleBucket
from apps.casework_web.views import REQUESTER_COOKIE
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider

WEB_SETTINGS = {
    "ROOT_URLCONF": "apps.casework_web.urls",
    "ALLOWED_HOSTS": ["127.0.0.1", "testserver", "localhost"],
    "MIDDLEWARE": [
        "apps.casework_web.guard.CaseworkGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    "FATWA_CASEWORK_WEB_ENABLED": True,
    "CSRF_COOKIE_NAME": "fatwa_casework_csrf",
    "CSRF_COOKIE_PATH": "/casework/",
    "CSRF_COOKIE_SAMESITE": "Strict",
    "CSRF_COOKIE_HTTPONLY": True,
    "CSRF_COOKIE_SECURE": False,
    "DATA_UPLOAD_MAX_MEMORY_SIZE": 262144,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 12,
    "DEBUG": False,
}


class Directory(MuftiIdentityProvider):
    """Test-only directory populated by trusted fixture code, never web inputs."""
    provider_id = "synthetic-case-directory"
    credential = "M" * 64

    def __init__(self):
        self.current = MuftiIdentity(
            "fixture-mufti", "MUFTI", True, frozenset({"unassigned"}), "epoch-1",
            timezone.now() + timedelta(minutes=30),
        )

    def grant(self, *public_refs):
        self.current = replace(self.current, case_keys=frozenset(public_refs))

    def authenticate(self, credential):
        return self.current if credential == self.credential else None

    def resolve(self, subject_id):
        return self.current if subject_id == self.current.subject_id else None


def hidden(response, name):
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]*)"', response.content.decode())
    if match is None:
        raise AssertionError("expected form field missing: " + name)
    return unescape(match.group(1))


def post(client, path, fields, page):
    values = {"csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), **fields}
    return client.post(path, urlencode(values), content_type="application/x-www-form-urlencoded")


@override_settings(**WEB_SETTINGS)
class CaseworkHTTPTests(TransactionTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.directory = Directory()
        self.identity_settings = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.identity_settings.enable()
        self.addCleanup(self.identity_settings.disable)

    def intake(self, question="سؤال اصطناعي محفوظ كما وصل.  ", client=None):
        client = client or self.client
        page = client.get("/casework/")
        fields = {
            "question": question, "request_id": hidden(page, "request_id"),
            "confirmation": hidden(page, "confirmation"),
        }
        response = post(client, "/casework/", fields, page)
        self.assertEqual(response.status_code, 200, response.content)
        case = Case.objects.get(idempotency_key=fields["request_id"])
        token = re.search(r'id="issued-token">([^<]+)', response.content.decode()).group(1)
        return case, token, response, fields, page

    def login(self):
        page = self.client.get("/casework/staff/login/")
        response = post(self.client, "/casework/staff/login/", {
            "credential": self.directory.credential,
        }, page)
        self.assertEqual(response.status_code, 303, response.content)
        return self.client.get("/casework/staff/")

    def open_case(self, case, page):
        response = post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": case.public_ref,
        }, page)
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def mutation(self, page, action, **extra):
        return post(self.client, "/casework/staff/", {
            "action": action, "case_ref": hidden(page, "case_ref"),
            "revision": hidden(page, "revision"),
            "evidence_version": hidden(page, "evidence_version"), **extra,
        }, page)

    def check_token(self, token, client=None):
        client = client or self.client
        page = client.get("/casework/status/")
        return post(client, "/casework/status/", {"token": token}, page)

    def test_two_intakes_original_exact_public_ref_and_idempotent_replay(self):
        original = "  سُؤالٌ اصطناعي؟\nلا تُعدّل لغته.  "
        alpha, token, response, fields, page = self.intake(original)
        beta, _, _, _, _ = self.intake("سؤال مستقل ثانٍ")
        self.assertNotEqual(alpha.pk, beta.pk)
        self.assertNotEqual(alpha.public_ref, beta.public_ref)
        self.assertEqual(alpha.source.original_question, original)
        self.assertNotIn(str(alpha.pk), response.content.decode())
        self.assertNotIn(alpha.requester_id, response.content.decode())
        replay = post(self.client, "/casework/", fields, page)
        self.assertEqual(replay.status_code, 200)
        self.assertNotIn(token, replay.content.decode())
        self.assertEqual(Case.objects.count(), 2)
        tampered = post(self.client, "/casework/", {**fields, "question": "تغيير"}, page)
        self.assertEqual(tampered.status_code, 409)
        self.assertEqual(Case.objects.get(pk=alpha.pk).source.original_question, original)

    def test_csrf_rejects_mutations_and_denials_are_private(self):
        response = self.client.post("/casework/", {"question": "x"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(Case.objects.count(), 0)
        self.assertEqual(self.client.get("/casework/followup/").status_code, 405)

    def test_closed_profile_remote_and_query_rejections(self):
        self.assertEqual(self.client.get("/casework/?token=anything").status_code, 400)
        self.assertEqual(self.client.get("/casework/", REMOTE_ADDR="192.0.2.8").status_code, 403)
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=False):
            self.assertEqual(self.client.get("/casework/").status_code, 503)
        self.assertEqual(self.client.put("/casework/").status_code, 405)
        self.assertEqual(self.client.get("/casework/missing/").status_code, 404)
        self.assertEqual(self.client.post(
            "/casework/", "x", content_type="application/x-www-form-urlencoded",
            CONTENT_LENGTH="262145",
        ).status_code, 413)

    def test_unknown_and_nonliteral_hosts_rejected_before_reading_or_writing(self):
        for host in ("attacker.example", "localhost", "127.0.0.1.attacker.example"):
            response = self.client.get("/casework/", HTTP_HOST=host)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(host, response.content.decode())
            self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        self.assertEqual(Case.objects.count(), 0)

    def test_intake_binds_identity_and_rejects_client_role_and_invalid_proof(self):
        page = self.client.get("/casework/")
        fields = {"question": "x", "request_id": hidden(page, "request_id"),
                  "confirmation": hidden(page, "confirmation")}
        self.assertEqual(post(self.client, "/casework/", {**fields, "role": "MUFTI"}, page).status_code, 400)
        self.assertEqual(post(self.client, "/casework/", {**fields, "confirmation": "ع" * 64}, page).status_code, 400)
        self.assertEqual(post(self.client, "/casework/", {**fields, "confirmation": "0" * 64}, page).status_code, 403)
        self.assertEqual(Case.objects.count(), 0)

    def test_requester_token_scope_never_echoes_secrets_or_private_content(self):
        alpha, alpha_token, _, _, _ = self.intake("PRIVATE ALPHA ORIGINAL")
        beta, beta_token, _, _, _ = self.intake("PRIVATE BETA ORIGINAL")
        response = self.check_token(alpha_token)
        self.assertContains(response, alpha.public_ref)
        for forbidden in [str(alpha.pk), str(beta.pk), beta.public_ref, alpha_token, beta_token,
                          "PRIVATE ALPHA ORIGINAL", "PRIVATE BETA ORIGINAL", "RECEIVED"]:
            self.assertNotIn(forbidden, response.content.decode())
        self.assertEqual(self.check_token(alpha.public_ref).status_code, 404)
        page = self.client.get("/casework/status/")
        self.assertEqual(post(self.client, "/casework/status/", {
            "token": alpha_token, "case_ref": beta.public_ref,
        }, page).status_code, 400)

    def test_staff_auth_role_confusion_and_cross_case_reads_writes(self):
        alpha, _, _, _, _ = self.intake()
        beta, _, _, _, _ = self.intake("PRIVATE BETA")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.directory.grant(alpha.public_ref)
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        page = self.client.get("/casework/staff/login/")
        self.assertEqual(post(self.client, "/casework/staff/login/", {
            "credential": self.directory.credential,
        }, page).status_code, 403)
        self.directory.current = replace(self.directory.current, role="MUFTI")
        page = self.login()
        self.assertNotIn(beta.public_ref, page.content.decode())
        for action in ("open", "rotate"):
            self.assertEqual(post(self.client, "/casework/staff/", {
                "action": action, "case_ref": beta.public_ref,
            }, page).status_code, 403)
        self.assertEqual(post(self.client, "/casework/staff/", {
            "action": "open", "case_ref": alpha.public_ref, "subject_id": "other",
        }, page).status_code, 400)
        self.assertEqual(CaseEvent.objects.filter(case=beta).count(), 1)

    def test_staff_cookie_invalidates_on_epoch_provider_and_csrf_binding_change(self):
        alpha, _, _, _, _ = self.intake()
        self.directory.grant(alpha.public_ref)
        self.login()
        other = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        other.get("/casework/staff/login/")
        other.cookies[COOKIE] = self.client.cookies[COOKIE].value
        self.assertEqual(other.get("/casework/staff/").status_code, 403)
        self.directory.current = replace(self.directory.current, auth_epoch="epoch-2")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.login()
        self.directory.provider_id = "different-directory"
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)

    def test_auth_epoch_change_between_cookie_check_and_core_call_rejects_write(self):
        from apps.casework_web.access import current_staff
        alpha, _, _, _, _ = self.intake()
        self.directory.grant(alpha.public_ref)
        page = self.open_case(alpha, self.login())
        def revoke_after_cookie_validation(*args, **kwargs):
            identity = current_staff(*args, **kwargs)
            self.directory.current = replace(self.directory.current, auth_epoch="epoch-revoked")
            return identity
        with patch("apps.casework_web.views.current_staff", side_effect=revoke_after_cookie_validation):
            response = self.mutation(page, "draft", text="must not be saved")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(alpha.answers.count(), 0)
        self.assertEqual(alpha.events.count(), 1)

    def test_connected_clarification_followup_human_answer_and_approval(self):
        alpha, token, _, _, _ = self.intake("ORIGINAL UNCHANGED")
        self.directory.grant(alpha.public_ref)
        page = self.open_case(alpha, self.login())
        page = self.mutation(page, "clarify", text="ما التفصيل الإضافي؟")
        self.assertEqual(page.status_code, 200, page.content)
        status_page = self.check_token(token)
        self.assertContains(status_page, "ما التفصيل الإضافي؟")
        result = post(self.client, "/casework/followup/", {
            "token": token, "text": "تعقيب اصطناعي", "revision": hidden(status_page, "revision"),
        }, status_page)
        self.assertEqual(result.status_code, 200, result.content)
        page = self.open_case(alpha, self.client.get("/casework/staff/"))
        self.assertContains(page, "ORIGINAL UNCHANGED")
        self.assertContains(page, "تعقيب اصطناعي")
        page = self.mutation(page, "draft", text="مسودة بشرية اصطناعية وليست فتوى.")
        self.assertEqual(page.status_code, 200, page.content)
        page = self.mutation(page, "approve", answer_id=hidden(page, "answer_id"), note="")
        self.assertEqual(page.status_code, 200, page.content)
        result = self.check_token(token)
        self.assertContains(result, "اكتملت مراجعة الجواب")
        self.assertNotContains(result, "الجواب متاح")
        self.assertNotContains(result, "مسودة بشرية")
        self.assertEqual(CaseSource.objects.get(case=alpha).original_question, "ORIGINAL UNCHANGED")
        alpha.refresh_from_db()
        self.assertEqual(alpha.evidence_version, 2)
        self.assertIsNotNone(alpha.approved_answer_id)

    def test_stale_web_form_rejected_without_partial_answer(self):
        alpha, token, _, _, _ = self.intake()
        self.directory.grant(alpha.public_ref)
        page = self.open_case(alpha, self.login())
        services.add_followup(token=token, text="new facts", expected_revision=1, synthetic_fixtures_only=True)
        response = self.mutation(page, "draft", text="stale answer")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(alpha.answers.count(), 0)

    def test_trusted_recovery_rotates_and_revoke_removes_access(self):
        alpha, token, _, _, _ = self.intake()
        self.directory.grant(alpha.public_ref)
        page = self.open_case(alpha, self.login())
        fields = {"action": "rotate", "case_ref": alpha.public_ref}
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=None):
            self.assertEqual(post(self.client, "/casework/staff/", fields, page).status_code, 503)
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=lambda *args: "wrong-binding"):
            self.assertEqual(post(self.client, "/casework/staff/", fields, page).status_code, 409)
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=lambda *args: alpha.requester_id):
            response = post(self.client, "/casework/staff/", fields, page)
            self.assertEqual(response.status_code, 200, response.content)
            replacement = re.search(r'id="replacement-token">([^<]+)', response.content.decode()).group(1)
            self.assertEqual(self.check_token(token).status_code, 404)
            self.assertEqual(self.check_token(replacement).status_code, 200)
            response = post(self.client, "/casework/staff/", {
                "action": "revoke", "case_ref": alpha.public_ref,
            }, response)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.check_token(replacement).status_code, 404)

    def test_shared_database_rate_budget_ignores_forwarded_addresses(self):
        page = self.client.get("/casework/status/")
        for _ in range(30):
            response = post(self.client, "/casework/status/", {"token": "invalid"}, page)
            self.assertEqual(response.status_code, 404)
        other = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7")
        page = other.get("/casework/status/")
        response = post(other, "/casework/status/", {"token": "invalid"}, page)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "60")
        self.assertLessEqual(ThrottleBucket.objects.count(), 2)

    def test_requester_cookie_is_opaque_and_httponly(self):
        page = self.client.get("/casework/")
        cookie = page.cookies[REQUESTER_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/casework/")
        # Client cookie is signed; application accepts it only via get_signed_cookie.
        self.client.cookies[REQUESTER_COOKIE] = "rq_" + "0" * 32
        response = post(self.client, "/casework/", {
            "question": "x", "request_id": hidden(page, "request_id"),
            "confirmation": hidden(page, "confirmation"),
        }, page)
        self.assertEqual(response.status_code, 400)
