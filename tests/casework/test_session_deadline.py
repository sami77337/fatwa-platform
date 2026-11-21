"""Browser expiry stays authoritative when a directory identity lives longer."""

import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services
from apps.casework.models import AnswerRevision, CaseDecision, CaseEvent, CaseSource
from apps.casework_web import access
from apps.mufti_review.identity import IdentityUnavailable
from tests.casework import test_http as http


@override_settings(**http.WEB_SETTINGS)
class StaffSessionDeadlineTests(TransactionTestCase):
    def setUp(self):
        key = uuid.uuid4().hex
        self.receipt = services.intake_case(
            original_question="سؤال حرفي  محفوظ\nلا يتغير بانتهاء الجلسة.",
            source_event_id=key,
            requester_id="fixture-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        self.directory = http.Directory()
        self.directory.grant(self.receipt["public_ref"])
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        self.assertEqual(
            http.post(
                self.client,
                "/casework/staff/login/",
                {"credential": self.directory.credential},
                page,
            ).status_code,
            303,
        )
        self.page = self.client.get("/casework/staff/")
        self.assertEqual(self.page.status_code, 200)
        self.request = self.page.wsgi_request
        saved = self.request.get_signed_cookie(access.COOKIE, salt=access.SALT, max_age=access.TTL)
        self.until = datetime.fromisoformat(json.loads(saved)["until"])

    def proxy(self):
        actor = access.current_staff(self.request, self.directory)
        return access.RequestDirectory(
            self.directory, actor, authenticated_provider_id=self.directory.provider_id
        )

    def test_current_staff_caps_directory_identity_to_exact_cookie_deadline(self):
        actor = access.current_staff(self.request, self.directory)
        self.assertEqual(actor.valid_until, self.until)
        self.assertGreater(self.directory.current.valid_until, self.until)

    def test_current_staff_rechecks_cookie_expiry_after_a_slow_identity_lookup(self):
        original = self.directory.resolve
        later = self.until + timedelta(seconds=1)
        elapsed = patch("apps.casework_web.access.timezone.now", return_value=later)

        def slow(subject):
            elapsed.start()
            return original(subject)

        try:
            with patch.object(self.directory, "resolve", side_effect=slow):
                with self.assertRaises(IdentityUnavailable):
                    access.current_staff(self.request, self.directory)
        finally:
            elapsed.stop()

    def test_proxy_resolution_cannot_extend_expired_session_with_same_epoch(self):
        proxy = self.proxy()
        later = self.until + timedelta(seconds=1)
        self.directory.current = replace(
            self.directory.current, valid_until=later + timedelta(minutes=20)
        )
        with patch("apps.casework_web.access.timezone.now", return_value=later):
            with self.assertRaises(IdentityUnavailable):
                proxy.resolve(self.directory.current.subject_id)

    def test_pure_projection_rejects_session_expiry_even_without_a_directory_change(self):
        proxy = self.proxy()
        before = self.directory.projection_epoch()
        with patch(
            "apps.casework_web.access.timezone.now", return_value=self.until + timedelta(seconds=1)
        ):
            self.assertEqual(before, self.directory.projection_epoch())
            with self.assertRaises(IdentityUnavailable):
                proxy.projection_epoch()

    def test_valid_directory_refresh_cannot_extend_browser_deadline(self):
        proxy = self.proxy()
        self.directory.current = replace(
            self.directory.current, valid_until=timezone.now() + timedelta(minutes=45)
        )
        self.assertEqual(proxy.resolve(self.directory.current.subject_id).valid_until, self.until)
        shorter = timezone.now() + timedelta(minutes=2)
        self.directory.current = replace(self.directory.current, valid_until=shorter)
        self.assertEqual(proxy.resolve(self.directory.current.subject_id).valid_until, shorter)

    def test_expiry_while_mutation_waits_for_case_lock_preserves_all_original_rows(self):
        before = list(CaseSource.objects.values())
        original_case, original_save = services._case, services.save_answer
        writing, elapsed = [False], []

        def save(**values):
            writing[0] = True
            return original_save(**values)

        def locked(*args, **kwargs):
            row = original_case(*args, **kwargs)
            if writing[0] and kwargs.get("lock") is True and not elapsed:
                clock = patch(
                    "apps.casework_web.access.timezone.now",
                    return_value=self.until + timedelta(seconds=1),
                )
                clock.start()
                elapsed.append(clock)
            return row

        try:
            with (
                patch.object(services, "save_answer", side_effect=save),
                patch.object(services, "_case", side_effect=locked),
            ):
                response = http.post(
                    self.client,
                    "/casework/staff/",
                    {
                        "action": "draft",
                        "case_ref": self.receipt["public_ref"],
                        "revision": "1",
                        "evidence_version": "1",
                        "text": "محاولة لا تحفظ بعد الانتهاء",
                    },
                    self.page,
                )
        finally:
            for clock in elapsed:
                clock.stop()
        self.assertTrue(elapsed)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(list(CaseSource.objects.values()), before)
        self.assertEqual(
            (
                AnswerRevision.objects.count(),
                CaseDecision.objects.count(),
                CaseEvent.objects.count(),
            ),
            (0, 0, 1),
        )
