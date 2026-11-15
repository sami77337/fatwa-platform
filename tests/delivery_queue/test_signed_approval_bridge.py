"""End-to-end signed MUFTI receipt to atomic PostgreSQL consumption."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from base64 import urlsafe_b64encode
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.db import connection
from django.test import TransactionTestCase

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence, require_return_approval
from apps.delivery_planner.planner import Authority, Capabilities, Choice, InvalidPlan, Part, plan_delivery
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier, IdentityStatus, SignedApprovalReceipt,
    approval_signing_payload, canonical_plan_sha256,
)
from apps.delivery_queue.approval_adapter import commit_signed_approved_plan
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent


ISSUER = "trusted-identity.example"
AUDIENCE = "fatwa-platform.return.v1"
KEY_ID = "mufti-ed25519-2026-01"
SUBJECT = "mufti-pg-test-01"
A, B, C = "a"*64, "b"*64, "c"*64


@unittest.skipUnless(connection.vendor == "postgresql", "requires PostgreSQL 17/18")
class SignedApprovalPostgresBridgeTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.now = datetime.now(UTC)
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.evidence = CurrentEvidence("signed-pg-case", 5, A, B, "")
        self.plan = self.make_plan(C)
        self.revoked = False
        self.identity = IdentityStatus(SUBJECT, "MUFTI", True)
        self.receipt = self.make_receipt(self.plan)
        self.verifier = self.make_verifier()

    def make_plan(self, digest):
        return plan_delivery(
            case_key="signed-pg-case", source_peer_key="thread:signed-pg-1",
            parts=(Part(1, "text", digest, 24),),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 200, True),
            authority=Authority(5, A, True), choice=Choice(),
        )

    def make_receipt(self, plan, **changes):
        claims = dict(
            case_key="signed-pg-case",
            answer_revision=5,
            answer_sha256=A,
            source_digest=B,
            reply_digest="",
            approver_id=SUBJECT,
            approver_role="MUFTI",
            decision="APPROVE_RETURN_TO_ORIGIN",
            receipt_id="signed-pg-receipt-01",
            issued_at=(self.now - timedelta(seconds=5)).isoformat(),
            issuer=ISSUER,
            audience=AUDIENCE,
            key_id=KEY_ID,
            expires_at=(self.now + timedelta(minutes=4)).isoformat(),
            nonce="N"*43,
            plan_sha256=canonical_plan_sha256(plan),
            signature_b64url="",
        )
        claims.update(changes)
        unsigned = SignedApprovalReceipt(**claims)
        signature = urlsafe_b64encode(
            self.private.sign(approval_signing_payload(unsigned))
        ).decode("ascii").rstrip("=")
        return replace(unsigned, signature_b64url=signature)

    def make_verifier(self):
        return Ed25519ApprovalVerifier(
            issuer=ISSUER, audience=AUDIENCE,
            trusted_public_keys={KEY_ID: self.public},
            identity_lookup=lambda subject: self.identity if subject == SUBJECT else None,
            is_revoked_or_consumed=lambda receipt_id, nonce, key_id: self.revoked,
            clock=lambda: self.now,
        )

    def commit(self, receipt=None, plan=None):
        return commit_signed_approved_plan(
            receipt=receipt or self.receipt,
            evidence=self.evidence,
            plan=plan or self.plan,
            verify_receipt=self.verifier,
        )

    def test_signed_mufti_receipt_is_verified_then_consumed_atomically(self):
        first = self.commit()
        second = self.commit()
        self.assertEqual([row.intent_key for row in first], [row.intent_key for row in second])
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), 1)
        claim = ApprovalClaim.objects.get()
        expected = require_return_approval(
            receipt=self.receipt, evidence=self.evidence, plan=self.plan,
            verify_receipt=self.verifier,
        )
        self.assertEqual(claim.receipt_id, self.receipt.receipt_id)
        self.assertEqual(claim.approval_fingerprint, expected.approval_fingerprint)
        self.assertEqual(claim.plan_fingerprint, canonical_plan_sha256(self.plan))

    def test_signed_receipt_cannot_authorize_a_changed_plan(self):
        changed = self.make_plan(B)
        with self.assertRaisesRegex(InvalidPlan, "approval_not_bound_to_exact_delivery_plan"):
            self.commit(plan=changed)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_revoked_or_inactive_mufti_cannot_consume_postgres_claim(self):
        self.revoked = True
        with self.assertRaisesRegex(InvalidPlan, "approval_signature_or_identity_not_verified"):
            self.commit()
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.revoked = False
        self.identity = IdentityStatus(SUBJECT, "MUFTI", False)
        with self.assertRaisesRegex(InvalidPlan, "approval_signature_or_identity_not_verified"):
            self.commit()
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_tampered_signature_and_unsigned_legacy_receipt_are_rejected(self):
        tampered = replace(self.receipt, answer_sha256=C)
        with self.assertRaisesRegex(InvalidPlan, "approval_not_bound_to_current_evidence"):
            self.commit(receipt=tampered)
        unsigned = ApprovalReceipt(
            "signed-pg-case", 5, A, B, "", SUBJECT, "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "unsigned-pg-receipt",
            self.receipt.issued_at,
        )
        with self.assertRaisesRegex(ValueError, "signed_mufti_receipt_required"):
            self.commit(receipt=unsigned)
        self.assertEqual(ApprovalClaim.objects.count(), 0)


if __name__ == "__main__":
    unittest.main()
