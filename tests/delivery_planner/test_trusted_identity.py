"""Ed25519 approval conformance tests using ephemeral test-only keys."""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence, require_return_approval
from apps.delivery_planner.outbox import stage_plan, reserve_for_adapter
from apps.delivery_planner.planner import Authority, Capabilities, Choice, InvalidPlan, Part, plan_delivery
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier, IdentityStatus, SignedApprovalReceipt, approval_signing_payload,
)

A, B, C = "a" * 64, "b" * 64, "c" * 64
ISSUER, AUDIENCE, KEY_ID, SUBJECT = (
    "trusted-identity.example", "fatwa-platform.return.v1", "mufti-key-2026-01", "mufti-test-001"
)


class TrustedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.identity = IdentityStatus(SUBJECT, "MUFTI", True)
        self.revoked = set()
        self.evidence = CurrentEvidence("intake-7", 3, A, B, "")
        self.plan = self.make_plan()
        self.receipt = self.make_receipt()
        self.verifier = self.make_verifier()

    def make_plan(self):
        return plan_delivery(
            case_key="intake-7", source_peer_key="thread:Q1",
            parts=(Part(1, "text", C, 20),),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 100, True),
            authority=Authority(3, A, True), choice=Choice(),
        )

    def make_receipt(self, **changes):
        base = ApprovalReceipt(
            "intake-7", 3, A, B, "", SUBJECT, "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "approval-2026-001",
            (self.now - timedelta(seconds=10)).isoformat(),
        )
        claims = dict(
            issuer=ISSUER, audience=AUDIENCE, key_id=KEY_ID,
            expires_at=(self.now + timedelta(minutes=4)).isoformat(),
            nonce="N" * 43, signature_b64url="",
        )
        claims.update(changes)
        unsigned = SignedApprovalReceipt(
            base.case_key, base.answer_revision, base.answer_sha256, base.source_digest,
            base.reply_digest, base.approver_id, base.approver_role, base.decision,
            base.receipt_id, base.issued_at, **claims
        )
        signature = base64.urlsafe_b64encode(
            self.private.sign(approval_signing_payload(unsigned))
        ).decode("ascii").rstrip("=")
        return replace(unsigned, signature_b64url=signature)

    def make_verifier(self, *, identities=None, revoked_key_ids=frozenset(), keys=None):
        return Ed25519ApprovalVerifier(
            issuer=ISSUER, audience=AUDIENCE, trusted_public_keys=keys or {KEY_ID: self.public},
            identity_lookup=lambda subject: (identities or {SUBJECT: self.identity}).get(subject),
            is_revoked_or_consumed=lambda rid, nonce, kid: (rid, nonce, kid) in self.revoked,
            revoked_key_ids=revoked_key_ids, clock=lambda: self.now,
        )

    def test_valid_signature_binds_exact_mufti_and_current_evidence(self):
        approved = require_return_approval(
            receipt=self.receipt, evidence=self.evidence, plan=self.plan, verify_receipt=self.verifier
        )
        self.assertEqual(approved.receipt_id, self.receipt.receipt_id)
        self.assertEqual(approved.case_key, "intake-7")
        self.assertEqual(len(approved.approval_fingerprint), 64)
        self.assertTrue(approved.authority.evidence_verified)

    def test_signature_tampering_and_unsigned_legacy_receipt_fail(self):
        self.assertFalse(self.verifier(replace(self.receipt, answer_sha256=C)))
        self.assertFalse(self.verifier(replace(self.receipt, signature_b64url="A" * 86)))
        self.assertFalse(self.verifier(ApprovalReceipt(
            "intake-7", 3, A, B, "", SUBJECT, "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "legacy", self.receipt.issued_at,
        )))

    def test_wrong_issuer_audience_role_and_decision_fail(self):
        for receipt in (
            self.make_receipt(issuer="attacker.example"),
            self.make_receipt(audience="other-service"),
            self.make_receipt(decision="TECHNICAL_REVIEW_COMPLETE"),
            self.make_receipt(approver_role="ORGANIZER"),
        ):
            self.assertFalse(self.verifier(receipt))

    def test_expired_future_stale_and_overlong_receipts_fail(self):
        for changes in (
            {"expires_at": (self.now - timedelta(seconds=1)).isoformat()},
            {"issued_at": (self.now + timedelta(minutes=2)).isoformat()},
            {"issued_at": (self.now - timedelta(minutes=20)).isoformat()},
            {"expires_at": (self.now + timedelta(hours=2)).isoformat()},
        ):
            self.assertFalse(self.make_verifier()(self.make_receipt(**changes)))

    def test_unknown_or_revoked_key_and_revoked_receipt_fail(self):
        self.assertFalse(self.make_verifier(keys={})(self.receipt))
        self.assertFalse(self.make_verifier(revoked_key_ids=frozenset({KEY_ID}))(self.receipt))
        self.revoked.add((self.receipt.receipt_id, self.receipt.nonce, self.receipt.key_id))
        self.assertFalse(self.verifier(self.receipt))

    def test_identity_must_be_active_mufti_and_lookup_failure_is_not_clearance(self):
        for identity in (
            None, IdentityStatus(SUBJECT, "ORGANIZER", True),
            IdentityStatus(SUBJECT, "MUFTI", False),
            IdentityStatus("other-subject", "MUFTI", True),
        ):
            self.assertFalse(self.make_verifier(identities={SUBJECT: identity})(self.receipt))
        broken = Ed25519ApprovalVerifier(
            issuer=ISSUER, audience=AUDIENCE, trusted_public_keys={KEY_ID: self.public},
            identity_lookup=lambda _: (_ for _ in ()).throw(RuntimeError("identity unavailable")),
            is_revoked_or_consumed=lambda *_: False, clock=lambda: self.now,
        )
        with self.assertRaises(RuntimeError):
            broken(self.receipt)

    def test_revocation_lookup_failure_fails_closed(self):
        broken = Ed25519ApprovalVerifier(
            issuer=ISSUER, audience=AUDIENCE, trusted_public_keys={KEY_ID: self.public},
            identity_lookup=lambda _: self.identity,
            is_revoked_or_consumed=lambda *_: (_ for _ in ()).throw(RuntimeError("revocation unavailable")),
            clock=lambda: self.now,
        )
        with self.assertRaises(RuntimeError):
            broken(self.receipt)

    def test_key_rotation_accepts_new_key_and_rejects_retired_key(self):
        new_private = Ed25519PrivateKey.generate()
        new_public = new_private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        new_id = "mufti-key-2026-02"
        new_receipt = self.make_receipt(key_id=new_id)
        new_receipt = replace(new_receipt, signature_b64url=base64.urlsafe_b64encode(
            new_private.sign(approval_signing_payload(new_receipt))
        ).decode("ascii").rstrip("="))
        rotated = self.make_verifier(keys={KEY_ID: self.public, new_id: new_public})
        self.assertTrue(rotated(self.receipt))
        self.assertTrue(rotated(new_receipt))
        retired = self.make_verifier(
            keys={KEY_ID: self.public, new_id: new_public}, revoked_key_ids=frozenset({KEY_ID})
        )
        self.assertFalse(retired(self.receipt))
        self.assertTrue(retired(new_receipt))

    def test_ed25519_verifier_integrates_with_outbox_stage_and_reservation(self):
        with TemporaryDirectory() as tmp:
            rows = stage_plan(
                Path(tmp), plan=self.plan, approval=self.receipt, evidence=self.evidence,
                verify_approval=self.verifier, synthetic_fixtures_only=True,
            )
            claim = reserve_for_adapter(
                Path(tmp), intent_key=rows[0].intent_key, plan=self.plan,
                approval=self.receipt, evidence=self.evidence, verify_approval=self.verifier,
                get_current_evidence=lambda case: self.evidence if case == "intake-7" else None,
                synthetic_fixtures_only=True,
            )
            self.assertEqual(claim.intent_key, rows[0].intent_key)

    def test_revoked_receipt_cannot_stage_and_creates_no_outbox_file(self):
        self.revoked.add((self.receipt.receipt_id, self.receipt.nonce, self.receipt.key_id))
        with TemporaryDirectory() as tmp:
            with self.assertRaises(InvalidPlan):
                stage_plan(
                    Path(tmp), plan=self.plan, approval=self.receipt, evidence=self.evidence,
                    verify_approval=self.verifier, synthetic_fixtures_only=True,
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
