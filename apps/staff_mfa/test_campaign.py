"""Native primary-only isolation, TOTP confirmation and current actual-role access."""

import time
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework.models import CaseEvidence, CaseSource
from apps.casework_web import access
from apps.casework_web.guard import LIMITS
from apps.staff_sessions import middleware as session_middleware
from apps.staff_sessions.models import Session
from tests.casework import test_http as http

from . import services, views
from .models import (
    Attempt,
    Challenge,
    Factor,
    FactorRevocation,
    Proof,
    RecoveryCode,
    RecoveryUse,
    SessionAssurance,
)
from .native_test_support import NATIVE, NativeFixture
from .test_support import PASSWORDS


@override_settings(**NATIVE)
class NativeMfaTests(NativeFixture, TransactionTestCase):
    def counts(self):
        return tuple(
            model.objects.count()
            for model in (
                Challenge,
                Factor,
                Proof,
                Attempt,
                RecoveryCode,
                RecoveryUse,
                FactorRevocation,
                SessionAssurance,
            )
        )

    def test_both_actual_roles_must_finish_totp_before_their_native_workspaces(self):
        before = list(CaseSource.objects.values()), list(CaseEvidence.objects.values())
        for subject, surface, status in (("mufti", "CASEWORK", 403), ("admin", "OPERATIONS", 409)):
            client, page = self.primary(subject, surface=surface)
            self.assertEqual(client.get(views.HOMES[surface]).status_code, status)
            baseline = self.counts()
            self.assertEqual(client.get(views.PATHS[surface]).status_code, 200)
            self.assertEqual(client.head(views.PATHS[surface]).status_code, 200)
            self.assertEqual(self.counts(), baseline)
            factor, page = self.enroll_native(client, page, surface=surface)
            hidden = client.get(views.PATHS[surface])
            self.assertNotContains(hidden, 'id="mfa-manual-key"')
            self.verify_native(client, page, factor, surface=surface)
            allowed = client.get(views.HOMES[surface])
            self.assertEqual(allowed.status_code, 200, allowed.content)
            self.assertContains(allowed, self.receipt["public_ref"])
            self.assertEqual(client.get(views.PATHS[surface]).status_code, 200)
        self.assertEqual(Session.objects.count(), 2)
        self.assertEqual(
            (list(CaseSource.objects.values()), list(CaseEvidence.objects.values())), before
        )

    def test_native_wrong_token_no_cookie_then_success_and_replay_denial(self):
        client, page = self.primary()
        factor, page = self.enroll_native(client, page)
        self.assertEqual(
            http.post(
                client, views.PATHS["CASEWORK"], {"action": "verify", "code": "1"}, page
            ).status_code,
            403,
        )
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(Attempt.objects.filter(accepted=False).count(), 1)
        self.assertFalse(client.cookies.get(access.COOKIE) and client.cookies[access.COOKIE].value)
        page = client.get(views.PATHS["CASEWORK"])
        self.verify_native(client, page, factor)
        second, pending = self.primary()
        refused = http.post(
            second,
            views.PATHS["CASEWORK"],
            {"action": "verify", "code": self.used_otp(factor)},
            pending,
        )
        self.assertEqual(refused.status_code, 403, refused.content)
        self.assertEqual(Session.objects.count(), 1)
        self.assertEqual(client.get(views.HOMES["CASEWORK"]).status_code, 200)

    def test_pending_cookie_is_browser_bound_and_never_a_staff_or_other_surface_cookie(self):
        client, page = self.primary()
        stolen = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        stolen.cookies[views.cookie("CASEWORK")] = client.cookies[views.cookie("CASEWORK")].value
        self.assertEqual(stolen.get(views.PATHS["CASEWORK"]).status_code, 403)
        self.assertEqual(stolen.get(views.HOMES["CASEWORK"]).status_code, 403)
        client.cookies[views.cookie("OPERATIONS")] = client.cookies[views.cookie("CASEWORK")].value
        self.assertEqual(client.get(views.PATHS["OPERATIONS"]).status_code, 403)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(Factor.objects.count(), 0)

    def test_native_saved_recovery_replaces_factor_without_preserving_old_session(self):
        original, _, factor, codes = self.enroll_login()
        client, page = self.primary()
        before = Session.objects.count()
        page = http.post(
            client, views.PATHS["CASEWORK"], {"action": "recover", "recovery_code": codes[0]}, page
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(Session.objects.count(), before)
        self.assertEqual(original.get(views.HOMES["CASEWORK"]).status_code, 403)
        self.assertEqual(client.get(views.HOMES["CASEWORK"]).status_code, 403)
        replacement, page = self.enroll_native(client, page)
        self.assertNotEqual(replacement.pk, factor.pk)
        self.verify_native(client, page, replacement)
        self.assertEqual(client.get(views.HOMES["CASEWORK"]).status_code, 200)
        self.assertEqual(RecoveryUse.objects.count(), 1)
        self.assertEqual(FactorRevocation.objects.count(), 1)

    def test_native_fresh_factor_revocation_blocks_copied_session_and_enrollment_bootstrap(self):
        client, _, factor, _ = self.enroll_login()
        copied = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        copied.cookies = client.cookies.copy()
        page = client.get(views.PATHS["CASEWORK"])
        self.assertEqual(page.status_code, 200, page.content)
        page = http.post(
            client,
            views.PATHS["CASEWORK"],
            {"action": "revoke_start", "credential": PASSWORDS["mufti"]},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.verify_native(client, page, factor, offset=0, expected=303)
        self.assertEqual(copied.get(views.HOMES["CASEWORK"]).status_code, 403)
        _, pending = self.primary()
        self.assertNotContains(pending, "تسجيل عامل تحقق لهذا الحساب")
        self.assertContains(pending, "استرداد العامل برمز محفوظ")

    def test_factor_revocation_fresh_primary_cannot_switch_to_another_account(self):
        client, _, _, _ = self.enroll_login()
        page = client.get(views.PATHS["CASEWORK"])
        before = Challenge.objects.count()
        response = http.post(
            client,
            views.PATHS["CASEWORK"],
            {"action": "revoke_start", "credential": PASSWORDS["other"]},
            page,
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(Challenge.objects.count(), before)
        self.assertEqual(FactorRevocation.objects.count(), 0)

    def test_native_post_render_policy_revocation_withholds_login_and_mfa_never_grants_case_read(
        self,
    ):
        client, page = self.primary()
        factor, page = self.enroll_native(client, page)
        render = views.render
        rendered = []

        def revoke_after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            if args[2].get("completed"):
                rendered.append(True)
                self.authority.denied.add("VERIFY")
            return response

        with patch("apps.staff_mfa.views.render", side_effect=revoke_after_render):
            response = http.post(
                client,
                views.PATHS["CASEWORK"],
                {"action": "verify", "code": self.otp(factor)},
                page,
            )
        self.assertEqual(rendered, [True])
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(Proof.objects.count(), 0)
        self.assertNotContains(response, "mfa-recovery-codes", status_code=403)
        self.authority.denied.clear()
        client, _, _, _ = self.enroll_login()
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=True, FATWA_DATA_PRIVACY_AUTHORITY=None):
            response = client.get(views.HOMES["CASEWORK"])
            self.assertEqual(response.status_code, 200, response.content)
            self.assertNotContains(response, self.receipt["public_ref"])

    def test_mfa_forms_share_the_existing_primary_credential_budget(self):
        now = time.time()
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        with patch("apps.casework_web.guard.time.time", return_value=now):
            for index in range(LIMITS["login"]):
                route = views.PATHS["CASEWORK" if index % 2 else "OPERATIONS"]
                self.assertEqual(
                    http.post(client, route, {"action": "invalid"}, page).status_code, 400
                )
            for route in views.PATHS.values():
                self.assertEqual(
                    http.post(client, route, {"action": "invalid"}, page).status_code, 429
                )
        self.assertEqual(self.counts(), (0,) * 8)

    def test_seed_is_withheld_when_enrollment_authority_is_revoked_after_render(self):
        client, page = self.primary()
        render = views.render
        rendered = []

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            if args[2].get("manual_key"):
                rendered.append(True)
                self.authority.denied.add("ENROLL")
            return response

        with patch("apps.staff_mfa.views.render", side_effect=revoke):
            response = http.post(client, views.PATHS["CASEWORK"], {"action": "enroll"}, page)
        self.assertEqual(rendered, [True])
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotContains(response, "mfa-manual-key", status_code=403)
        self.assertEqual(Factor.objects.count(), 1)
        self.assertEqual(Proof.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)

    def test_enrollment_grant_deadline_survives_later_start_projection_and_render(self):
        client, page = self.primary()
        render, now = views.render, timezone.now()
        rendered = []

        def after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            if args[2].get("manual_key"):
                rendered.append(True)
            return response

        def deadline(**values):
            return (
                now + timedelta(seconds=1) if values["action"] == "ENROLL" else self.authority.until
            )

        with (
            patch.object(self.authority, "grant_deadline", side_effect=deadline),
            patch(
                "apps.staff_mfa.services.timezone.now",
                side_effect=lambda: now + timedelta(seconds=2) if rendered else now,
            ),
            patch("apps.staff_mfa.views.render", side_effect=after_render),
        ):
            response = http.post(client, views.PATHS["CASEWORK"], {"action": "enroll"}, page)
        self.assertEqual(rendered, [True])
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotContains(response, "mfa-manual-key", status_code=403)

    def test_pending_factor_revoked_after_render_is_not_presented_as_current(self):
        factor, _, _, _ = self.enrolled()
        client, _ = self.primary()
        revoking = self.start(purpose="REVOKE")
        render = views.render
        rendered = []

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            if args[2].get("pending") and not rendered:
                rendered.append(True)
                with services.complete(revoking.id, code=self.otp(factor), **self.common()) as (
                    grant,
                    _,
                ):
                    services.revoke(grant)
            return response

        with patch("apps.staff_mfa.views.render", side_effect=revoke):
            response = client.get(views.PATHS["CASEWORK"])
        self.assertEqual(rendered, [True])
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotContains(response, "mfa-code", status_code=403)
        self.assertEqual(FactorRevocation.objects.count(), 1)

    def test_preauthentication_pins_survive_to_outer_pure_final_without_a_staff_binding(self):
        client, page = self.primary()
        original = session_middleware._check
        outer = []

        def change_after_view(lease, response):
            self.assertContains(response, "mfa-manual-key")
            self.assertEqual(lease.bindings, {})
            self.assertTrue(lease.final_guards)
            outer.append(True)
            self.authority.denied.add("ENROLL")
            with (
                patch.object(
                    self.authority, "permits", side_effect=AssertionError("late policy callback")
                ),
                patch.object(
                    self.directory, "resolve", side_effect=AssertionError("late directory callback")
                ),
            ):
                original(lease, response)

        with patch("apps.staff_sessions.middleware._check", side_effect=change_after_view):
            response = http.post(client, views.PATHS["CASEWORK"], {"action": "enroll"}, page)
        self.assertEqual(outer, [True])
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json(), {"error": "staff_mfa_not_authorized"})
        self.assertNotContains(response, "mfa-manual-key", status_code=404)

    def test_issued_cookie_is_withheld_if_mfa_changes_after_complete_before_outer_final(self):
        client, page = self.primary()
        factor, page = self.enroll_native(client, page)
        original = session_middleware._check
        outer = []

        def change_after_complete(lease, response):
            self.assertEqual(Session.objects.count(), 1)
            self.assertContains(response, "mfa-recovery-codes")
            self.assertEqual(lease.bindings, {})
            outer.append(True)
            self.authority.denied.add("USE")
            original(lease, response)

        with patch("apps.staff_sessions.middleware._check", side_effect=change_after_complete):
            response = http.post(
                client,
                views.PATHS["CASEWORK"],
                {"action": "verify", "code": self.otp(factor)},
                page,
            )
        self.assertEqual(outer, [True])
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotContains(response, "mfa-recovery-codes", status_code=404)
        self.assertFalse(client.cookies.get(access.COOKIE) and client.cookies[access.COOKIE].value)
        # The completed proof remains immutable history; its response and cookie
        # were never delivered. A new login must perform two factors again.
        self.assertEqual(Session.objects.count(), 1)
        self.assertEqual(Proof.objects.count(), 1)

    def test_short_mfa_proof_expiry_is_retained_beyond_longer_challenge_and_session(self):
        self.authority.rule = replace(self.authority.rule, session_seconds=10)
        client, page = self.primary()
        factor, page = self.enroll_native(client, page)
        original = session_middleware._check
        outer = []

        def expire_after_complete(lease, response):
            proof = Proof.objects.get(factor=factor)
            self.assertLess(proof.expires_at, Session.objects.get().expires_at)
            self.assertLess(proof.expires_at, proof.challenge.expires_at)
            outer.append(True)
            with patch(
                "apps.staff_mfa.services.timezone.now",
                return_value=proof.expires_at + timedelta(milliseconds=1),
            ):
                original(lease, response)

        with patch("apps.staff_sessions.middleware._check", side_effect=expire_after_complete):
            response = http.post(
                client,
                views.PATHS["CASEWORK"],
                {"action": "verify", "code": self.otp(factor)},
                page,
            )
        self.assertEqual(outer, [True])
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotContains(response, "mfa-recovery-codes", status_code=404)
        self.assertFalse(client.cookies.get(access.COOKIE) and client.cookies[access.COOKIE].value)

    def test_managed_factor_revocation_during_final_session_callback_withholds_page(self):
        client, _, factor, _ = self.enroll_login()
        revoking = self.start(purpose="REVOKE")
        render = views.render
        rendered, revoked = [], []

        def after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            if args[2].get("managed"):
                rendered.append(True)
            return response

        def revoke_during_session_callback(values):
            if values["action"] == "USE" and rendered and not revoked:
                revoked.append(True)
                with services.complete(revoking.id, code=self.otp(factor), **self.common()) as (
                    grant,
                    _,
                ):
                    services.revoke(grant)

        self.session_authority.hook = revoke_during_session_callback
        with patch("apps.staff_mfa.views.render", side_effect=after_render):
            response = client.get(views.PATHS["CASEWORK"])
        self.assertEqual(rendered, [True])
        self.assertEqual(revoked, [True])
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotContains(response, "mfa-managed", status_code=403)
        self.assertEqual(FactorRevocation.objects.count(), 1)
