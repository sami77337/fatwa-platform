"""Trusted recovery is a real PostgreSQL workflow, but the verifier is synthetic."""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from .models import UsedRecoveryAssertion
from .recovery import (
    TrustedRecoveryAuthority,
    VerifiedRecovery,
    recover_lost_access,
)

URL = "/casework/status/"
SETTINGS = {**WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls"}


class SyntheticRecoveryAuthority(TrustedRecoveryAuthority):
    """Test-only out-of-band identity proof; never configured in the application."""

    issuer_id = "synthetic-independent-identity"
    credential = "verified-" + "v" * 56

    def __init__(self, case, *, assertion_id=None):
        now = timezone.now()
        self.claim = VerifiedRecovery(
            issuer_id=self.issuer_id,
            audience="fatwa.casework.private-recovery.v1",
            assertion_id=assertion_id or "claim-" + "q" * 58,
            public_ref=case["public_ref"],
            requester_id=case["requester_id"],
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        self.available = True
        self.calls = 0

    def verify(self, credential, public_ref):
        self.calls += 1
        if not self.available or credential != self.credential:
            return None
        return self.claim


class TrustedRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.case = self.intake("a")
        self.authority = SyntheticRecoveryAuthority(self.case)

    def intake(self, suffix):
        result = cases.intake_case(
            original_question="  أصل السؤال محفوظ\\n" + suffix,
            source_event_id="recovery-source-" + suffix,
            requester_id="recovery-requester-" + suffix,
            idempotency_key="recovery-intake-" + suffix,
            synthetic_fixtures_only=True,
        )
        return {**result, "requester_id": "recovery-requester-" + suffix}

    def recover(self, case=None, authority=None, credential=None):
        return recover_lost_access(
            public_ref=(case or self.case)["public_ref"],
            credential=credential or self.authority.credential,
            authority=authority or self.authority,
            synthetic_fixtures_only=True,
        )

    def test_verified_assertion_rotates_tokens_without_changing_original_case(self):
        original = Case.objects.get(pk=self.case["case_id"])
        question = original.source.original_question
        self.assertEqual(original.revision, 1)
        result = self.recover()
        self.assertTrue(result["rotated"])
        self.assertNotEqual(result["token"], self.case["token"])
        with self.assertRaises(cases.CaseConflict):
            cases.requester_status(self.case["token"], synthetic_fixtures_only=True)
        fresh = cases.requester_status(result["token"], synthetic_fixtures_only=True)
        self.assertEqual(fresh["public_ref"], self.case["public_ref"])
        self.assertEqual(fresh["revision"], 2)
        original.refresh_from_db()
        self.assertEqual(original.source.original_question, question)
        self.assertEqual(original.evidence.count(), 1)
        self.assertEqual(original.answers.count(), 0)
        self.assertEqual(list(original.events.values_list("action", flat=True)),
                         ["INTAKE", "ROTATE_ACCESS"])
        self.assertEqual(UsedRecoveryAssertion.objects.filter(case=original).count(), 1)
        saved = UsedRecoveryAssertion.objects.get()
        self.assertNotIn(self.authority.credential, str(saved.__dict__))
        self.assertNotIn(self.authority.claim.assertion_id, str(saved.__dict__))
        self.assertEqual(
            saved.digest,
            sha256((self.authority.issuer_id + ":" +
                    self.authority.claim.assertion_id).encode("ascii")).hexdigest(),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            UsedRecoveryAssertion.objects.filter(pk=saved.pk).update(issuer_id="tampered")
        self.assertEqual(UsedRecoveryAssertion.objects.get().issuer_id, self.authority.issuer_id)

    def test_replay_wrong_case_missing_authority_and_expired_claim_do_not_mutate(self):
        other = self.intake("b")
        for authority, credential, case in (
            (None, self.authority.credential, self.case),
            (self.authority, "invalid-" + "0" * 55, self.case),
            (self.authority, self.authority.credential, other),
        ):
            if authority is None:
                with self.assertRaises(cases.CaseConflict):
                    recover_lost_access(
                        public_ref=case["public_ref"], credential=credential,
                        authority=None, synthetic_fixtures_only=True,
                    )
            else:
                with self.assertRaises(cases.CaseConflict):
                    self.recover(case=case, authority=authority, credential=credential)
        original_case = Case.objects.get(pk=self.case["case_id"])
        self.assertEqual(original_case.revision, 1)
        self.assertEqual(UsedRecoveryAssertion.objects.count(), 0)
        expired = SyntheticRecoveryAuthority(self.case)
        expired.claim = replace(
            expired.claim, issued_at=timezone.now() - timedelta(minutes=20),
            expires_at=timezone.now() - timedelta(minutes=10),
        )
        with self.assertRaises(cases.CaseConflict):
            self.recover(authority=expired)
        self.assertEqual(UsedRecoveryAssertion.objects.count(), 0)
        issued = self.recover()
        with self.assertRaises(cases.CaseConflict):
            self.recover()
        self.assertEqual(UsedRecoveryAssertion.objects.count(), 1)
        self.assertEqual(
            cases.requester_status(issued["token"], synthetic_fixtures_only=True)["revision"],
            2,
        )

    def test_recovery_rollback_and_concurrent_reuse_are_fail_closed(self):
        self.authority.available = False
        with self.assertRaises(cases.CaseConflict):
            self.recover()
        self.authority.available = True

        def attempt():
            close_old_connections()
            try:
                try:
                    return self.recover()["token"]
                except cases.CaseConflict:
                    return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: attempt(), range(2)))
        issued = [token for token in outcomes if token is not None]
        self.assertEqual(len(issued), 1)
        self.assertEqual(UsedRecoveryAssertion.objects.count(), 1)
        self.assertEqual(
            cases.requester_status(issued[0], synthetic_fixtures_only=True)["revision"],
            2,
        )
        with self.assertRaises(cases.CaseConflict):
            cases.requester_status(self.case["token"], synthetic_fixtures_only=True)


@override_settings(**SETTINGS)
class TrustedRecoveryHTTPTests(TransactionTestCase):
    def setUp(self):
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        self.case = cases.intake_case(
            original_question="SECRET ORIGINAL QUESTION",
            source_event_id="http-recovery-source",
            requester_id="http-recovery-owner",
            idempotency_key="http-recovery-idempotency",
            synthetic_fixtures_only=True,
        )
        self.owner = {**self.case, "requester_id": "http-recovery-owner"}
        self.authority = SyntheticRecoveryAuthority(self.owner)

    def submit(self, page, *, credential=None, case_ref=None, extra=None):
        fields = {
            "action": "trusted_recover",
            "public_ref": case_ref or self.case["public_ref"],
            "credential": credential or self.authority.credential,
            "recovery_nonce": hidden(page, "recovery_nonce"),
            "recovery_proof": hidden(page, "recovery_proof"),
            **(extra or {}),
        }
        return post(self.client, URL, fields, page)

    def test_lost_token_recovered_from_ui_with_one_time_receipt_and_private_cookie(self):
        with override_settings(FATWA_CASEWORK_RECOVERY_AUTHORITY=self.authority):
            page = self.client.get(URL)
            self.assertContains(page, 'id="trusted-recovery"')
            self.assertContains(page, 'id="recover-credential"')
            self.assertNotContains(page, "SECRET ORIGINAL QUESTION")
            self.assertIn("no-store", page["Cache-Control"])
            confirmed = self.submit(page)
            self.assertEqual(confirmed.status_code, 200)
            match = re.search(r'id="recovered-token">([^<]+)', confirmed.content.decode())
            self.assertIsNotNone(match)
            token = match.group(1)
            self.assertTrue(token.startswith("rt_"))
            self.assertEqual(UsedRecoveryAssertion.objects.count(), 1)
            self.assertTrue(confirmed.cookies["fatwa_casework_private"]["httponly"])
            self.assertContains(self.client.get(URL), self.case["public_ref"])
            self.assertNotContains(self.client.get(URL), token)
            # V7 exposes the owner's question only after trusted recovery has
            # issued and bound a valid new capability; the anonymous check above
            # still verifies that it cannot leak before authentication.
            self.assertContains(self.client.get(URL), "SECRET ORIGINAL QUESTION")
            with self.assertRaises(cases.CaseConflict):
                cases.requester_status(self.case["token"], synthetic_fixtures_only=True)
            self.assertEqual(self.submit(page).status_code, 404)
            self.assertEqual(UsedRecoveryAssertion.objects.count(), 1)

    def test_no_trusted_verifier_no_csrf_wrong_case_and_injected_role_denied(self):
        page = self.client.get(URL)
        self.assertNotContains(page, 'id="recover-credential"')
        with self.assertRaises(cases.CaseConflict):
            recover_lost_access(
                public_ref=self.case["public_ref"],
                credential=self.authority.credential,
                authority=None,
                synthetic_fixtures_only=True,
            )
        with override_settings(FATWA_CASEWORK_RECOVERY_AUTHORITY=self.authority):
            page = self.client.get(URL)
            self.assertEqual(self.client.post(URL, {
                "action": "trusted_recover", "public_ref": self.case["public_ref"],
                "credential": self.authority.credential,
            }).status_code, 403)
            self.assertEqual(self.submit(page, extra={"role": "MUFTI"}).status_code, 404)
            self.assertEqual(
                self.submit(page, case_ref="FT-2026-" + "A" * 20).status_code, 404
            )
            self.assertEqual(
                self.submit(page, credential="wrong-" + "a" * 60).status_code, 404
            )
        self.assertEqual(UsedRecoveryAssertion.objects.count(), 0)
        self.assertEqual(Case.objects.get(pk=self.case["case_id"]).revision, 1)
