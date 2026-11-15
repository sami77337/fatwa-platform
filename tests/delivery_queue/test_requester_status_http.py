"""Private requester tracking via CSRF-protected POST, never via URL token."""
from __future__ import annotations

from datetime import timedelta
from html import unescape
from urllib.parse import urlencode
from unittest.mock import patch
import os
import re

from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.delivery_queue import requester_tracking as tracking
from apps.delivery_queue.models import (
    RequesterTrackingEvent, RequesterTrackingToken,
)

BASE = "/requester/tracking/"


@override_settings(
    ROOT_URLCONF="apps.delivery_queue.requester_urls",
    ALLOWED_HOSTS=["testserver", "127.0.0.1"],
    MIDDLEWARE=[
        "apps.delivery_queue.requester_http.RequesterTrackingGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    CSRF_COOKIE_NAME="fatwa_tracking_csrf",
    CSRF_COOKIE_PATH="/requester/",
    CSRF_COOKIE_SAMESITE="Strict",
    CSRF_COOKIE_HTTPONLY=True,
    FATWA_REQUESTER_TRACKING_ENABLED=True,
)
class RequesterStatusHttpTests(TransactionTestCase):
    def setUp(self):
        self.alpha = tracking.provision_tracking_case(
            case_key="case-alpha",
            operator_id="synthetic-operator",
            authorize_operator=lambda actor, case: actor == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.beta = tracking.provision_tracking_case(
            case_key="case-beta",
            operator_id="synthetic-operator",
            authorize_operator=lambda actor, case: actor == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client = Client(enforce_csrf_checks=True)

    def _csrf(self, response):
        source = response.content.decode("utf-8")
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', source)
        self.assertIsNotNone(match)
        return unescape(match.group(1))

    def _post(self, token, **extra):
        landing = self.client.get(BASE)
        fields = {"csrfmiddlewaretoken": self._csrf(landing), "token": token}
        fields.update(extra)
        return self.client.post(
            BASE, data=urlencode(fields), content_type="application/x-www-form-urlencoded",
        )

    def test_default_disabled_without_any_database_access(self):
        with override_settings(FATWA_REQUESTER_TRACKING_ENABLED=False), CaptureQueriesContext(connection) as queries:
            response = self.client.get(BASE)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(queries), 0)

    def test_two_tokens_only_reveal_their_own_coarse_state(self):
        response = self._post(self.alpha)
        self.assertEqual(response.status_code, 200)
        self.assertIn("تم استلام السؤال".encode("utf-8"), response.content)
        self.assertNotIn(b"RECEIVED", response.content)
        for secret in (self.alpha, self.beta, b"case-alpha", b"case-beta"):
            needle = secret.encode() if isinstance(secret, str) else secret
            self.assertNotIn(needle, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        tracking.advance_tracking_case(
            case_key="case-beta", expected_revision=1, stage="UNDER_REVIEW",
            actor_id="synthetic-operator", authorize_actor=lambda *args: True,
        )
        beta = self._post(self.beta)
        self.assertIn("قيد المراجعة".encode("utf-8"), beta.content)
        self.assertNotIn(b"case-beta", beta.content)

    def test_invalid_or_expired_token_does_not_disclose_case_existence(self):
        unknown = self._post("rt_" + "Z" * 43)
        self.assertEqual(unknown.status_code, 404)
        self.assertNotIn(b"case-", unknown.content)
        tracking.rotate_tracking_token(
            case_key="case-alpha", operator_id="synthetic-operator",
            authorize_operator=lambda *args: True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        revoked = self._post(self.alpha)
        self.assertEqual(revoked.status_code, 404)
        self.assertEqual(unknown.content, revoked.content)

    def test_token_in_query_string_is_denied(self):
        response = self.client.get(BASE + "?token=" + self.alpha)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(self.alpha.encode(), response.content)

    def test_csrf_required_and_no_mutating_get_or_post_on_css(self):
        self.assertEqual(self.client.post(BASE, data={"token":self.alpha}).status_code, 403)
        self.assertEqual(self.client.get(BASE + "status/").status_code, 404)
        self.assertEqual(self.client.post(BASE + "tracking.css", data={}).status_code, 405)
        self.assertEqual(self.client.put(BASE, data="x").status_code, 405)

    def test_no_mutation_from_successful_lookup(self):
        before = list(RequesterTrackingEvent.objects.values_list("pk", "new_stage"))
        tokens = list(RequesterTrackingToken.objects.values_list("token_sha256", "revoked_at"))
        response = self._post(self.alpha)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, list(RequesterTrackingEvent.objects.values_list("pk", "new_stage")))
        self.assertEqual(tokens, list(RequesterTrackingToken.objects.values_list("token_sha256", "revoked_at")))

    def test_remote_address_is_rejected_without_query(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(BASE, REMOTE_ADDR="198.51.100.5")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(queries), 0)

    def test_repeated_token_fields_are_denied(self):
        landing = self.client.get(BASE)
        data = urlencode([
            ("csrfmiddlewaretoken", self._csrf(landing)),
            ("token", self.alpha), ("token", self.beta),
        ])
        response = self.client.post(BASE, data=data, content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(self.alpha.encode(), response.content)
