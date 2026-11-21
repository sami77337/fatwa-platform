"""Actual campaign routes, CSRF-bound operational sessions and final native reads."""

import copy
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.casework.models import Case
from tests.casework.test_http import hidden, post

from . import access, views
from .test_support import CREDENTIALS, FEATURES, OperationalFixture

BASE = "/casework/operations/"


@override_settings(**FEATURES)
class OperationalWorkspaceHTTPTests(OperationalFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def login(self, subject="operator", client=None):
        client = client or self.client
        page = client.get(BASE + "login/")
        self.assertEqual(page.status_code, 200, page.content)
        response = post(client, BASE + "login/", {"credential": CREDENTIALS[subject]}, page)
        self.assertEqual(response.status_code, 303, response.content)
        return client.get(BASE)

    def test_real_campaign_login_filters_and_detail_have_actual_role_and_no_hidden_case_leak(self):
        page = self.login()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "ORGANIZER")
        self.assertEqual(self.client.cookies[access.COOKIE]["path"], BASE)
        self.assertTrue(self.client.cookies[access.COOKIE]["httponly"])
        for key in ("hidden", "unscoped"):
            self.assertNotContains(page, self.receipts[key]["public_ref"])
            self.assertNotContains(page, self.receipts[key]["case_id"])
        filtered = post(self.client, BASE, {"action": "queue", "filter": "delivery"}, page)
        self.assertContains(filtered, self.receipts["delivery"]["public_ref"])
        self.assertNotContains(filtered, self.receipts["metadata"]["public_ref"])
        detail = post(
            self.client,
            BASE,
            {
                "action": "detail",
                "case_ref": self.receipts["delivery"]["public_ref"],
                "section": "delivery",
            },
            filtered,
        )
        self.assertContains(detail, "فشل مسجل يحتاج مراجعة")
        self.assertContains(detail, 'id="ops-original"')
        self.assertNotContains(detail, 'name="answer"')
        self.assertNotContains(detail, 'value="APPROVE"')
        self.assertIn("no-store", detail["Cache-Control"])
        self.assertIn("default-src 'none'", detail["Content-Security-Policy"])
        self.assertEqual(self.state(), self.originals)

    def test_missing_csrf_unknown_duplicate_action_and_client_role_are_rejected(self):
        page = self.login()
        self.assertEqual(self.client.post(BASE, {"action": "queue"}).status_code, 403)
        for fields in (
            {"action": "APPROVE"},
            {"action": "queue", "role": "MUFTI"},
            {"action": "queue", "case_ref": self.receipts["hidden"]["public_ref"]},
            {
                "action": "detail",
                "case_ref": self.receipts["metadata"]["public_ref"],
                "section": "metadata",
                "extra": "x",
            },
        ):
            self.assertEqual(post(self.client, BASE, fields, page).status_code, 409)
        duplicate = (
            "csrfmiddlewaretoken="
            + hidden(page, "csrfmiddlewaretoken")
            + "&action=queue&action=detail"
        )
        self.assertEqual(
            self.client.post(
                BASE, duplicate, content_type="application/x-www-form-urlencoded"
            ).status_code,
            409,
        )
        self.assertEqual(self.state(), self.originals)

    def test_copying_session_without_original_csrf_binding_and_wrong_case_detail_are_denied(self):
        page = self.login()
        other = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        other.get(BASE + "login/")
        other.cookies[access.COOKIE] = self.client.cookies[access.COOKIE].value
        self.assertEqual(other.get(BASE).status_code, 409)
        for kind in ("hidden", "unscoped"):
            response = post(
                self.client,
                BASE,
                {
                    "action": "detail",
                    "case_ref": self.receipts[kind]["public_ref"],
                    "section": "metadata",
                },
                page,
            )
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(self.receipts[kind]["public_ref"], response.content.decode())
        self.assertEqual(self.state(), self.originals)

    def test_current_read_revocation_removes_counts_and_detail_then_identity_revocation_closes_session(
        self,
    ):
        page = self.login()
        self.authority.revoke(action="READ_PUBLICATION")
        fresh = post(self.client, BASE, {"action": "queue", "filter": "publication"}, page)
        self.assertContains(fresh, 'data-filter-count="publication">0</span>')
        self.assertNotContains(fresh, self.receipts["publication"]["public_ref"])
        response = post(
            self.client,
            BASE,
            {
                "action": "detail",
                "case_ref": self.receipts["publication"]["public_ref"],
                "section": "publication",
            },
            fresh,
        )
        self.assertEqual(response.status_code, 409)
        self.revoke_identity()
        self.assertEqual(self.client.get(BASE).status_code, 409)

    def test_late_native_render_history_append_rolls_back_and_discards_generated_private_body(self):
        page = self.login()
        original_render = views.render
        case = Case.objects.get(pk=self.receipts["metadata"]["case_id"])

        def changing(*args, **kwargs):
            response = original_render(*args, **kwargs)
            organization.save(
                case_id=str(case.pk),
                subject_id="mufti",
                provider=self.directory,
                tags=["وسم بعد القراءة"],
                question_types=["EDUCATION"],
                note="",
                command_id="00000000-0000-4000-8000-000000000002",
                expected_metadata_version=0,
                expected_revision=1,
                expected_evidence_version=1,
                synthetic_fixtures_only=True,
            )
            return response

        with patch.object(views, "render", side_effect=changing):
            response = post(
                self.client,
                BASE,
                {"action": "detail", "case_ref": case.public_ref, "section": "metadata"},
                page,
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(case.public_ref, response.content.decode())
        self.assertEqual(self.state(), self.originals)

    def test_native_render_directory_replacement_and_policy_revocation_cannot_reuse_generated_page(
        self,
    ):
        self.login()
        original_render = views.render
        old = settings.FATWA_CASEWORK_IDENTITY_PROVIDER

        def replacement(*args, **kwargs):
            response = original_render(*args, **kwargs)
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER = copy.copy(old)
            return response

        try:
            with patch.object(views, "render", side_effect=replacement):
                response = self.client.get(BASE)
            self.assertEqual(response.status_code, 409)
        finally:
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER = old

        def revoked(*args, **kwargs):
            response = original_render(*args, **kwargs)
            self.authority.revoke(action="READ_QUEUE")
            return response

        with patch.object(views, "render", side_effect=revoked):
            response = self.client.get(BASE)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(self.receipts["metadata"]["public_ref"], response.content.decode())
        self.assertEqual(self.state(), self.originals)

    def test_defaults_logout_and_existing_mufti_session_boundary_remain_closed(self):
        with override_settings(FATWA_OPERATIONAL_WORKSPACE_ENABLED=False):
            self.assertEqual(self.client.get(BASE + "login/").status_code, 404)
        page = self.login("admin")
        self.assertContains(page, "ORGANIZER_ADMIN")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        response = post(self.client, BASE + "logout/", {}, page)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get(BASE).status_code, 409)
