"""Existing enrollment is a veto on weaker authentication, never a role grant."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client, TransactionTestCase, override_settings

from apps.casework_web.access import COOKIE as STAFF_COOKIE
from apps.mufti_review.identity import authenticate_identity
from apps.operational_workspace import identity as operations
from apps.operational_workspace.access import COOKIE as OPERATIONS_COOKIE
from apps.staff_sessions.models import Session
from tests.casework import test_http as http

from . import services, views
from .models import Factor
from .native_test_support import NATIVE, NativeFixture
from .test_support import PASSWORDS


@override_settings(**NATIVE)
class MfaDowngradeTests(NativeFixture, TransactionTestCase):
    def legacy_login(self, subject, surface):
        # Verify the actual legacy contract, including its no-whitespace check,
        # before relying on a denial as MFA evidence. The same configured
        # directory verifies the fabricated PBKDF2 password in both flows.
        actor = (
            authenticate_identity(self.directory, PASSWORDS[subject])
            if surface == "CASEWORK"
            else operations.authenticate(self.directory, PASSWORDS[subject])
        )
        self.assertEqual(actor.subject_id, subject)
        cache.clear()
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        path = views.HOMES[surface] + "login/"
        page = client.get(path)
        self.assertEqual(page.status_code, 200, page.content)
        return client, http.post(client, path, {"credential": PASSWORDS[subject]}, page)

    def assert_no_cookie(self, client, surface):
        name = STAFF_COOKIE if surface == "CASEWORK" else OPERATIONS_COOKIE
        self.assertFalse(client.cookies.get(name) and client.cookies[name].value)

    def test_registered_accounts_cannot_get_new_password_only_cookies_after_switches_off(self):
        self.enrolled()
        self.enrolled("admin", surface="OPERATIONS")
        baseline = Session.objects.count()
        for sessions in (True, False):
            for subject, surface in (("mufti", "CASEWORK"), ("admin", "OPERATIONS")):
                with (
                    self.subTest(sessions=sessions, subject=subject),
                    override_settings(
                        FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=sessions
                    ),
                ):
                    client, response = self.legacy_login(subject, surface)
                    self.assertIn(response.status_code, {403, 409}, response.content)
                    self.assert_no_cookie(client, surface)
        self.assertEqual(Session.objects.count(), baseline)

    def test_cookies_from_before_enrollment_cannot_resume_after_enabling_then_disabling_mfa(self):
        legacy = []
        for sessions in (True, False):
            for subject, surface in (("mufti", "CASEWORK"), ("admin", "OPERATIONS")):
                with override_settings(
                    FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=sessions
                ):
                    client, response = self.legacy_login(subject, surface)
                    self.assertEqual(response.status_code, 303, response.content)
                    self.assertEqual(client.get(views.HOMES[surface]).status_code, 200)
                    legacy.append((sessions, surface, client))
        self.assertEqual(Factor.objects.count(), 0)
        self.enrolled()
        self.enrolled("admin", surface="OPERATIONS")
        for sessions, surface, client in legacy:
            with (
                self.subTest(sessions=sessions, surface=surface),
                override_settings(
                    FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=sessions
                ),
            ):
                response = client.get(views.HOMES[surface])
                self.assertIn(response.status_code, {403, 409}, response.content)
                self.assertNotIn(self.receipt["public_ref"], response.content.decode())

    def test_missing_app_key_or_authority_never_downgrades_an_existing_factor(self):
        self.enrolled()
        without_app = [name for name in settings.INSTALLED_APPS if name != "apps.staff_mfa"]
        variants = (
            {"FATWA_STAFF_MFA_KEY": None},
            {"FATWA_STAFF_MFA_AUTHORITY": None},
            {"INSTALLED_APPS": without_app},
            {"INSTALLED_APPS": without_app, "FATWA_STAFF_MFA_ENABLED": False},
            {
                "INSTALLED_APPS": without_app,
                "FATWA_STAFF_MFA_ENABLED": False,
                "FATWA_STAFF_SESSIONS_ENABLED": False,
            },
        )
        for configured in variants:
            with self.subTest(configured=tuple(configured)), override_settings(**configured):
                client, response = self.legacy_login("mufti", "CASEWORK")
                self.assertEqual(response.status_code, 403, response.content)
                self.assert_no_cookie(client, "CASEWORK")

    def test_an_account_with_no_factor_keeps_legacy_access_without_inheriting_another_factor(self):
        self.enrolled()
        without_app = [name for name in settings.INSTALLED_APPS if name != "apps.staff_mfa"]
        for sessions in (True, False):
            with (
                self.subTest(sessions=sessions),
                override_settings(
                    INSTALLED_APPS=without_app,
                    FATWA_STAFF_MFA_ENABLED=False,
                    FATWA_STAFF_SESSIONS_ENABLED=sessions,
                ),
            ):
                client, response = self.legacy_login("other", "CASEWORK")
                self.assertEqual(response.status_code, 303, response.content)
                self.assertEqual(client.get(views.HOMES["CASEWORK"]).status_code, 200)
        self.assertFalse(Factor.objects.filter(account__subject_id="other").exists())

    def test_pending_or_revoked_factor_history_does_not_reopen_legacy(self):
        pending = self.start()
        services.enroll(pending.id, **self.common())
        factor, _, _, _ = self.enrolled("other")
        revoking = self.start("other", purpose="REVOKE")
        with services.complete(revoking.id, code=self.otp(factor), **self.common()) as (grant, _):
            services.revoke(grant)
        with override_settings(FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=False):
            for subject in ("mufti", "other"):
                client, response = self.legacy_login(subject, "CASEWORK")
                self.assertEqual(response.status_code, 403, response.content)
                self.assert_no_cookie(client, "CASEWORK")

    def test_unavailable_history_never_falls_back_to_password_login(self):
        from . import history

        self.enrolled()
        with override_settings(FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=False):
            unavailable = SimpleNamespace(
                vendor="postgresql",
                cursor=Mock(side_effect=DatabaseError("synthetic history outage")),
            )
            with patch.object(history, "connection", unavailable):
                client, response = self.legacy_login("mufti", "CASEWORK")
            unavailable.cursor.assert_called_once()
            self.assertEqual(response.status_code, 403, response.content)
            self.assert_no_cookie(client, "CASEWORK")
