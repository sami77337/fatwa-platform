"""Role-separated local operator view never authorizes a delivery."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode
import os
import secrets
import sqlite3

from django.test import Client, SimpleTestCase, override_settings

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    FILE_NAME, list_intents, reserve_for_adapter, stage_plan,
)
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery
from apps.editorial_workbench import reviewer_settings as settings


@override_settings(
    SETTINGS_MODULE=settings.__name__,
    ROOT_URLCONF=settings.ROOT_URLCONF,
    MIDDLEWARE=settings.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class DeliveryOperatorViewTests(SimpleTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.operator_token = secrets.token_hex(32)
        self.author_token = secrets.token_hex(32)
        self.enterContext(patch.dict(os.environ, {
            "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(self.directory),
            "FATWA_SYNTHETIC_OPERATOR_TOKEN_SHA256": sha256(self.operator_token.encode()).hexdigest(),
            "FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256": sha256(self.author_token.encode()).hexdigest(),
        }))
        self.browser = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        self.url = "/review/operations/outbox/"

    def post(self, url, screen, data):
        return self.browser.post(
            url,
            urlencode({"csrfmiddlewaretoken": str(screen.context["csrf_token"]), **data}),
            content_type="application/x-www-form-urlencoded",
        )

    def login(self):
        path = "/review/operations/login/"
        screen = self.browser.get(path)
        response = self.post(path, screen, {"token": self.operator_token})
        self.assertEqual(response.status_code, 303)

    def prepare_reserved(self):
        a, b = "a" * 64, "b" * 64
        plan = plan_delivery(
            case_key="intake-7", source_peer_key="thread:Q1",
            parts=(Part(1, "text", b, 12),),
            capabilities=Capabilities("comment", "v1", frozenset({"text"}), 280, False),
            authority=Authority(2, a, True), choice=Choice(),
        )
        approval = ApprovalReceipt(
            "intake-7", 2, a, b, "", "mufti-test", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "decision-1", datetime.now(UTC).isoformat(),
        )
        evidence = CurrentEvidence("intake-7", 2, a, b, "")
        (intent,) = stage_plan(
            self.directory, plan=plan, approval=approval, evidence=evidence,
            verify_approval=lambda receipt: True, synthetic_fixtures_only=True,
        )
        reserve_for_adapter(
            self.directory, intent_key=intent.intent_key, plan=plan,
            approval=approval, evidence=evidence,
            verify_approval=lambda receipt: True,
            get_current_evidence=lambda case: evidence,
            synthetic_fixtures_only=True,
        )
        # Simulate an expired lease for the HTTP screen without sleeping.
        before = (datetime.now(UTC) - timedelta(seconds=10)).isoformat(timespec="microseconds")
        with sqlite3.connect(self.directory / FILE_NAME) as con:
            con.execute("UPDATE intents SET reservation_until=?", (before,))
        return intent

    def test_operator_login_is_distinct_and_empty_read_creates_no_file(self):
        unauthorized = self.browser.get(self.url)
        self.assertEqual(unauthorized.status_code, 302)
        self.login()
        page = self.browser.get(self.url)
        self.assertContains(page, "لا توجد محاولات معلّقة")
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.browser.post(self.url, {"action": "flag_expired"}).status_code, 403)

    def test_operator_can_quarantine_expired_attempt_not_send_it(self):
        intent = self.prepare_reserved()
        self.login()
        page = self.browser.get(self.url)
        self.assertContains(page, "UNCERTAIN_RESERVATION_EXPIRED")
        action = self.post(self.url, page, {"action": "flag_expired"})
        self.assertEqual(action.status_code, 303)
        refreshed = self.browser.get(self.url)
        self.assertContains(refreshed, "UNKNOWN_REQUIRES_RECONCILIATION")
        state = {entry.intent_key: entry.state for entry in list_intents(
            self.directory, synthetic_fixtures_only=True,
        )}
        self.assertEqual(state[intent.intent_key], "UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertNotContains(refreshed, 'name="action" value="send"')

    def test_author_identity_cannot_open_operator_records(self):
        intent = self.prepare_reserved()
        path = "/review/author/login/"
        screen = self.browser.get(path)
        self.assertEqual(self.post(path, screen, {"token": self.author_token}).status_code, 303)
        self.assertEqual(self.browser.get(self.url).status_code, 302)
        self.assertEqual(self.browser.post(self.url, {"action": "flag_expired"}).status_code, 403)
        self.assertEqual(
            list_intents(self.directory, synthetic_fixtures_only=True)[0].state,
            "RESERVED",
        )
