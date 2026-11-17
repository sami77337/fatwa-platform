import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services
from apps.casework.models import CaseDecision
from apps.casework_web.access import COOKIE
from apps.delivery_queue.models import ApprovalClaim, DeliveryAuditEvent, DeliveryIntent
from tests.casework.test_http import hidden, post

from .fixtures import CREDENTIAL, WEB_SETTINGS, DeskFixture

STAFF = "/casework/staff/"
LOGIN = STAFF + "login/"


@override_settings(**WEB_SETTINGS)
class DeliveryDeskHTTPTests(DeskFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def login(self):
        page = self.client.get(LOGIN)
        response = post(self.client, LOGIN, {"credential": CREDENTIAL}, page)
        self.assertEqual(response.status_code, 303)
        return self.client.get(STAFF)

    def action(self, page, action, **extra):
        return post(
            self.client, STAFF, {"action": action, "case_ref": self.a["public_ref"], **extra}, page
        )

    def test_full_native_export_signed_stage_report_and_quarantine(self):
        page = self.login()
        self.assertNotContains(page, self.foreign["public_ref"])
        page = self.action(page, "open")
        self.assertContains(page, "معاينة خطة الإرجاع")
        download = self.action(page, "export", max_chars="24", split="yes")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertIn("no-store", download["Cache-Control"])
        self.assertEqual(json.loads(download.content)["status"], "REQUEST_NOT_APPROVED")
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        page = self.action(page, "prepare", max_chars="24", split="yes")
        self.assertContains(page, "لم يُعتمد الإرجاع بعد")
        signed = self.signed_response()
        page = self.action(page, "stage", max_chars="24", split="yes", response_json=signed)
        self.assertContains(page, "حُفظت الخطة المعتمدة")
        self.assertContains(page, "مجهز ولم يُرسل")
        self.assertNotContains(page, signed)
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertTrue(all(row.state == "STAGED" for row in DeliveryIntent.objects.all()))
        lease = self.reserve()
        with patch(
            "django.utils.timezone.now", return_value=lease.expires_at + timedelta(seconds=1)
        ):
            page = self.action(page, "open")
            self.assertContains(page, "انتهت المهلة")
            response = self.action(
                page,
                "quarantine",
                plan_sha256=hidden(page, "plan_sha256"),
                confirmation="quarantine-expired-only",
            )
        self.assertContains(response, "نتيجة المحاولة غير محسومة")
        self.assertEqual(
            DeliveryIntent.objects.get(pk=lease.intent_key).state, "UNKNOWN_REQUIRES_RECONCILIATION"
        )
        self.record(lease)
        self.deliver()
        page = self.action(response, "open")
        self.assertContains(page, "تحققت جميع إثباتات التسليم")
        self.assertContains(page, "ليس إثبات قراءة السائل")
        for secret in (self.a["token"], self.foreign["public_ref"], lease.token, lease.intent_key):
            self.assertNotContains(page, secret)

    def test_disabled_loopback_host_query_and_method_boundaries(self):
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=False):
            self.assertEqual(self.client.get(STAFF).status_code, 503)
        self.assertEqual(self.client.get(STAFF, REMOTE_ADDR="203.0.113.1").status_code, 403)
        self.assertEqual(self.client.get(STAFF, HTTP_HOST="localhost").status_code, 400)
        self.assertEqual(self.client.get(STAFF + "?case_ref=x").status_code, 400)
        self.assertEqual(self.client.put(STAFF).status_code, 405)

    def test_authentication_csrf_and_foreign_scope_required(self):
        self.assertEqual(self.client.get(STAFF).status_code, 403)
        page = self.login()
        self.assertEqual(self.client.post(STAFF, {"action": "open"}).status_code, 403)
        result = post(
            self.client, STAFF, {"action": "open", "case_ref": self.foreign["public_ref"]}, page
        )
        self.assertEqual(result.status_code, 403)
        self.assertNotContains(result, self.foreign["public_ref"], status_code=403)

    def test_stale_identity_cookie_and_organizer_are_denied(self):
        self.login()
        self.directory.epoch = "changed"
        self.assertEqual(self.client.get(STAFF).status_code, 403)
        self.directory.epoch = "epoch-1"
        self.directory.role = "ORGANIZER_ADMIN"
        self.assertEqual(self.client.get(STAFF).status_code, 403)

    def test_no_approval_no_plan_controls_or_staging(self):
        page = self.login()
        services.add_followup(
            token=self.a["token"],
            text="تفصيل جديد",
            expected_revision=self.approved["revision"],
            synthetic_fixtures_only=True,
        )
        page = self.action(page, "open")
        self.assertContains(page, "لا يوجد جواب معتمد")
        self.assertNotContains(page, 'id="prepare-form"')
        result = self.action(page, "prepare", max_chars="24", split="yes")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_tampered_stale_or_unverified_signed_input_never_stages(self):
        page = self.login()
        signed = self.signed_response()
        data = json.loads(signed)
        data["receipt"]["signature_b64url"] = "x" * 86
        response = self.action(
            page, "stage", max_chars="24", split="yes", response_json=json.dumps(data)
        )
        self.assertEqual(response.status_code, 409)
        with override_settings(FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=None):
            response = self.action(page, "stage", max_chars="24", split="yes", response_json=signed)
            self.assertEqual(response.status_code, 409)
        response = self.action(page, "stage", max_chars="25", split="yes", response_json=signed)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_receipt_errors_do_not_echo_sensitive_input(self):
        page = self.login()
        response = self.action(
            page,
            "stage",
            max_chars="24",
            split="yes",
            response_json="SECRET-SYNTHETIC-INVALID-JSON",
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "SECRET-SYNTHETIC", status_code=400)
        self.assertNotContains(response, "Traceback", status_code=400)

    def test_quarantine_requires_exact_plan_and_explicit_confirmation(self):
        self.stage()
        lease = self.reserve()
        page = self.login()
        before = list(DeliveryAuditEvent.objects.values())
        with patch(
            "django.utils.timezone.now", return_value=lease.expires_at + timedelta(seconds=1)
        ):
            for fields, code in (
                ({"plan_sha256": "a" * 64, "confirmation": "quarantine-expired-only"}, 409),
                ({"plan_sha256": "a" * 64, "confirmation": ""}, 400),
            ):
                self.assertEqual(self.action(page, "quarantine", **fields).status_code, code)
        self.assertEqual(before, list(DeliveryAuditEvent.objects.values()))

    def test_duplicate_fields_roles_and_client_clock_are_rejected(self):
        page = self.login()
        self.assertEqual(self.action(page, "open", role="MUFTI").status_code, 400)
        body = (
            urlencode(
                {
                    "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                    "action": "open",
                    "case_ref": self.a["public_ref"],
                }
            )
            + "&case_ref=other"
        )
        self.assertEqual(
            self.client.post(
                STAFF, body, content_type="application/x-www-form-urlencoded"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.action(
                page,
                "quarantine",
                plan_sha256="a" * 64,
                confirmation="quarantine-expired-only",
                now="2099",
            ).status_code,
            400,
        )

    def test_private_headers_head_logout_and_no_secret_reflection(self):
        page = self.login()
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertIn("frame-ancestors 'none'", page["Content-Security-Policy"])
        self.assertNotContains(page, CREDENTIAL)
        self.assertEqual(self.client.head(STAFF).content, b"")
        result = post(self.client, STAFF + "logout/", {}, page)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(self.client.cookies[COOKIE].value, "")
        self.assertEqual(self.client.get(STAFF).status_code, 403)

    def test_export_and_refresh_are_domain_read_only(self):
        page = self.login()
        before = list(CaseDecision.objects.values())
        for action in ("prepare", "export"):
            self.assertEqual(
                self.action(page, action, max_chars="24", split="yes").status_code, 200
            )
        self.assertEqual(before, list(CaseDecision.objects.values()))
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryAuditEvent.objects.count(), 0)
