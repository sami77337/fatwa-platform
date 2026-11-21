"""Real PostgreSQL role/current-policy boundaries; no production authentication."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework.models import CaseEvidence, CaseSource
from apps.mufti_review.identity import IdentityUnavailable
from apps.staff_sessions import services as sessions

from . import services
from .models import (
    Account,
    Attempt,
    Challenge,
    Factor,
    FactorRevocation,
    Proof,
    RecoveryCode,
    RecoveryUse,
    SessionAssurance,
)
from .test_support import FEATURES, PASSWORDS, MfaFixture


@override_settings(**FEATURES)
class StaffMfaTests(MfaFixture, TransactionTestCase):
    def test_real_primary_and_totp_issue_exact_session_without_changing_originals(self):
        sources = list(CaseSource.objects.values()), list(CaseEvidence.objects.values())
        for subject, surface in (("mufti", "CASEWORK"), ("admin", "OPERATIONS")):
            factor, session_id, proof_id, codes = self.enrolled(subject, surface=surface)
            self.assertEqual(len(codes), 3)
            binding = self.bound(session_id, proof_id, subject, surface=surface)
            self.assertEqual(sessions.recheck(binding).subject_id, subject)
            self.assertEqual(sessions.recheck(binding).role, self.directory.resolve(subject).role)
            self.assertNotIn(
                codes[0], "".join(RecoveryCode.objects.values_list("canonical_payload", flat=True))
            )
            self.assertTrue(Factor.objects.filter(pk=factor.pk).exists())
        self.assertEqual(SessionAssurance.objects.count(), 2)
        self.assertEqual(
            (list(CaseSource.objects.values()), list(CaseEvidence.objects.values())), sources
        )

    def test_primary_only_missing_configuration_and_claimed_possession_cannot_issue(self):
        challenge = self.start()
        self.assertIsNone(challenge.factor_id)
        with self.assertRaises(IdentityUnavailable):
            sessions.issue(
                provider=self.directory,
                actor=self.directory.resolve("mufti"),
                surface="CASEWORK",
                browser_binding="c" * 64,
                deadline=self.directory.resolve("mufti").valid_until,
            )
        self.assertEqual(sessions.Session.objects.count(), 0)
        for values in (
            {"FATWA_STAFF_MFA_KEY": None},
            {"FATWA_STAFF_MFA_AUTHORITY": None},
            {"FATWA_STAFF_MFA_ENABLED": False},
            {"FATWA_STAFF_SESSIONS_ENABLED": False},
        ):
            with (
                self.subTest(values=values),
                override_settings(**values),
                self.assertRaises(IdentityUnavailable),
            ):
                self.start()
        self.directory.factor_kind = "POSSESSION"
        with self.assertRaises(IdentityUnavailable):
            self.start()

    def test_enrollment_is_once_shown_and_separate_permission(self):
        challenge = self.start()
        self.authority.denied.add("ENROLL")
        with self.assertRaises(IdentityUnavailable):
            services.enroll(challenge.id, **self.common())
        self.assertEqual(Factor.objects.count(), 0)
        self.authority.denied.clear()
        # Policy changes invalidate pending challenges even after the grant returns.
        challenge = self.start()
        services.enroll(challenge.id, **self.common())
        with self.assertRaises(IdentityUnavailable):
            services.enroll(challenge.id, **self.common())
        description = services.describe(challenge.id, **self.common())
        self.assertNotIn("secret", services.encode(description))
        self.assertEqual(Factor.objects.count(), 1)

    def test_wrong_otp_persists_account_attempts_across_fresh_primary_challenges(self):
        factor, _, _, _ = self.enrolled()
        for _ in range(self.authority.rule.max_failures):
            challenge = self.start()
            with (
                self.assertRaises(IdentityUnavailable),
                services.complete(challenge.id, code="xxxxxx", **self.common()),
            ):
                self.fail("invalid OTP yielded a grant")
        self.assertEqual(Attempt.objects.filter(accepted=False).count(), 3)
        challenge = self.start()
        with self.assertRaises(IdentityUnavailable):
            self.finish(challenge, factor)
        self.assertEqual(Proof.objects.count(), 1)

    def test_exact_counter_is_consumed_once_even_with_another_challenge(self):
        factor, _, _, _ = self.enrolled()
        challenge = self.start()
        with self.assertRaises(IdentityUnavailable):
            self.finish(challenge, factor, code=self.used_otp(factor))
        self.assertEqual(Attempt.objects.filter(accepted=False).count(), 1)
        self.finish(challenge, factor, offset=0)
        with self.assertRaises(IdentityUnavailable):
            self.finish(challenge, factor, offset=1)
        self.assertEqual(Proof.objects.count(), 2)

    def test_parallel_counter_accepts_one_exact_session_only(self):
        factor, _, _, _ = self.enrolled()
        first, second = self.start(), self.start()
        code = self.otp(factor)

        def run(identifier):
            connections.close_all()
            try:
                with services.complete(identifier, code=code, **self.common()) as (grant, _):
                    sessions.issue(
                        provider=self.directory,
                        actor=grant.guard.actor,
                        surface="CASEWORK",
                        browser_binding="c" * 64,
                        deadline=grant.proof.expires_at,
                        mfa_grant=grant,
                    )
                return "ACCEPTED"
            except IdentityUnavailable:
                return "DENIED"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(run, (first.id, second.id)))
        self.assertCountEqual(result, ["ACCEPTED", "DENIED"])
        self.assertEqual(Proof.objects.count(), 2)
        self.assertEqual(SessionAssurance.objects.count(), 2)

    def test_cross_browser_surface_actor_and_pending_epoch_are_denied(self):
        challenge = self.start()
        for values in ({"binding": "d" * 64}, {"surface": "OPERATIONS"}):
            with self.subTest(values=values), self.assertRaises(IdentityUnavailable):
                services.enroll(challenge.id, **self.common(**values))
        self.directory.identities["mufti"] = replace(
            self.directory.identities["mufti"], auth_epoch="epoch-2"
        )
        with self.assertRaises(IdentityUnavailable):
            services.enroll(challenge.id, **self.common())
        self.assertFalse(Factor.objects.exists())

    def test_expired_challenge_and_late_primary_identity_change_cannot_enroll(self):
        challenge = self.start()
        from unittest.mock import patch

        with (
            patch(
                "apps.staff_mfa.services.timezone.now",
                return_value=challenge.expires_at + timedelta(seconds=1),
            ),
            self.assertRaises(IdentityUnavailable),
        ):
            services.enroll(challenge.id, **self.common())
        self.directory.primary_hook = lambda: self.directory.identities.update(
            mufti=replace(self.directory.identities["mufti"], active=False)
        )
        with self.assertRaises(IdentityUnavailable):
            services.start(
                provider=self.directory,
                credential=PASSWORDS["mufti"],
                surface="CASEWORK",
                browser_binding="b" * 64,
            )

    def test_late_session_or_mfa_policy_revocation_rolls_back_proof_and_session(self):
        challenge = self.start()
        factor, _ = services.enroll(challenge.id, **self.common())
        before = (
            Proof.objects.count(),
            SessionAssurance.objects.count(),
            sessions.Session.objects.count(),
        )
        with self.assertRaises(IdentityUnavailable):
            with services.complete(challenge.id, code=self.otp(factor), **self.common()) as (
                grant,
                _,
            ):
                sessions.issue(
                    provider=self.directory,
                    actor=grant.guard.actor,
                    surface="CASEWORK",
                    browser_binding="c" * 64,
                    deadline=grant.proof.expires_at,
                    mfa_grant=grant,
                )
                self.session_authority.denied.add("ISSUE")
        self.assertEqual(
            (
                Proof.objects.count(),
                SessionAssurance.objects.count(),
                sessions.Session.objects.count(),
            ),
            before,
        )
        self.session_authority.denied.clear()
        with self.assertRaises(IdentityUnavailable):
            with services.complete(challenge.id, code=self.otp(factor), **self.common()) as (
                grant,
                _,
            ):
                sessions.issue(
                    provider=self.directory,
                    actor=grant.guard.actor,
                    surface="CASEWORK",
                    browser_binding="c" * 64,
                    deadline=grant.proof.expires_at,
                    mfa_grant=grant,
                )
                self.authority.denied.add("USE")
        self.assertEqual(
            (
                Proof.objects.count(),
                SessionAssurance.objects.count(),
                sessions.Session.objects.count(),
            ),
            before,
        )

    def test_revoke_factor_denies_existing_session_and_never_reopens_bootstrap(self):
        factor, session_id, proof_id, _ = self.enrolled()
        binding = self.bound(session_id, proof_id)
        challenge = self.start(purpose="REVOKE")
        with services.complete(challenge.id, code=self.otp(factor), **self.common()) as (grant, _):
            services.revoke(grant)
        with self.assertRaises(IdentityUnavailable):
            sessions.recheck(binding)
        fresh = self.start()
        with self.assertRaises(IdentityUnavailable):
            services.enroll(fresh.id, **self.common())
        with self.assertRaises(IdentityUnavailable):
            self.finish(fresh, factor, offset=1)

    def test_recovery_requires_password_and_independent_grant_then_verified_replacement(self):
        factor, session_id, proof_id, codes = self.enrolled()
        binding = self.bound(session_id, proof_id)
        challenge = self.start()
        self.authority.denied.add("RECOVER")
        with self.assertRaises(IdentityUnavailable):
            services.recover(challenge.id, recovery_code=codes[0], **self.common())
        self.assertFalse(RecoveryUse.objects.exists())
        self.authority.denied.clear()
        challenge = self.start()
        services.recover(challenge.id, recovery_code=codes[0], **self.common())
        with self.assertRaises(IdentityUnavailable):
            sessions.recheck(binding)
        self.assertEqual(SessionAssurance.objects.count(), 1)
        replacement, _ = services.enroll(challenge.id, **self.common())
        self.assertNotEqual(replacement.pk, factor.pk)
        self.finish(challenge, replacement)
        self.assertEqual(SessionAssurance.objects.count(), 2)
        with self.assertRaises(IdentityUnavailable):
            services.recover(challenge.id, recovery_code=codes[0], **self.common())
        self.assertEqual(RecoveryUse.objects.count(), 1)
        self.assertEqual(self.directory.resolve("mufti").role, "MUFTI")

    def test_stale_recovery_cannot_replace_a_later_revoked_factor_generation(self):
        _, _, _, codes = self.enrolled()
        stale, current = self.start(), self.start()
        services.recover(stale.id, recovery_code=codes[0], **self.common())
        services.recover(current.id, recovery_code=codes[1], **self.common())
        replacement, _ = services.enroll(current.id, **self.common())
        self.finish(current, replacement, offset=-1)
        revoking = self.start(purpose="REVOKE")
        with services.complete(revoking.id, code=self.otp(replacement), **self.common()) as (
            grant,
            _,
        ):
            services.revoke(grant)
        with self.assertRaises(IdentityUnavailable):
            services.enroll(stale.id, **self.common())
        self.assertEqual(Factor.objects.count(), 2)

    def test_current_mfa_config_and_actual_factor_revocation_are_retained_by_session(self):
        _, session_id, proof_id, _ = self.enrolled()
        binding = self.bound(session_id, proof_id)
        self.assertIsNotNone(sessions.check(binding))
        with (
            override_settings(FATWA_STAFF_MFA_ENABLED=False),
            self.assertRaises(IdentityUnavailable),
        ):
            sessions.check(binding)
        self.authority.hook = lambda values: self.session_authority.denied.add("USE")
        with self.assertRaises(IdentityUnavailable):
            sessions.check(binding)

    def test_session_policy_callback_cannot_revoke_factor_after_its_earlier_check(self):
        factor, session_id, proof_id, _ = self.enrolled()
        binding = self.bound(session_id, proof_id)
        challenge = self.start(purpose="REVOKE")
        fired = False

        def revoke_late(values):
            nonlocal fired
            if values["action"] == "USE" and not fired:
                fired = True
                with services.complete(challenge.id, code=self.otp(factor), **self.common()) as (
                    grant,
                    _,
                ):
                    services.revoke(grant)

        self.session_authority.hook = revoke_late
        with self.assertRaises(IdentityUnavailable):
            sessions.check(binding)
        self.assertTrue(fired)
        self.assertEqual(FactorRevocation.objects.count(), 1)

    def test_pure_final_check_keeps_exact_grant_expiry_without_replaying_callbacks(self):
        from unittest.mock import patch

        from django.utils import timezone

        _, session_id, proof_id, _ = self.enrolled()
        self.authority.until = timezone.now() + timedelta(seconds=2)
        binding = self.bound(session_id, proof_id)
        called = []
        self.authority.hook = lambda values: called.append(values)
        services.check(binding.mfa, authorize=False)
        with (
            patch(
                "apps.staff_mfa.services.timezone.now",
                return_value=self.authority.until + timedelta(milliseconds=1),
            ),
            self.assertRaises(IdentityUnavailable),
        ):
            services.check(binding.mfa, authorize=False)
        self.assertEqual(called, [])

    def test_history_is_immutable_and_recovery_code_rows_have_no_plaintext(self):
        _, _, _, codes = self.enrolled()
        challenge = self.start()
        services.recover(challenge.id, recovery_code=codes[0], **self.common())
        models = (
            Account,
            Challenge,
            Factor,
            Proof,
            Attempt,
            RecoveryCode,
            FactorRevocation,
            RecoveryUse,
            SessionAssurance,
        )
        for model in models:
            row = model.objects.first()
            self.assertIsNotNone(row)
            self.assertNotIn(codes[0], row.canonical_payload)
            for operation in ("UPDATE", "DELETE"):
                with (
                    self.subTest(model=model.__name__, operation=operation),
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                ):
                    table = connection.ops.quote_name(model._meta.db_table)
                    with connection.cursor() as cursor:
                        sql = (
                            f"UPDATE {table} SET digest=digest WHERE id=%s"
                            if operation == "UPDATE"
                            else f"DELETE FROM {table} WHERE id=%s"
                        )
                        cursor.execute(sql, [row.pk])
