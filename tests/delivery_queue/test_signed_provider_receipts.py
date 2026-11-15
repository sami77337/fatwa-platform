"""Offline signed provider receipts; synthetic PostgreSQL, no network sender."""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import patch
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.db import IntegrityError, connection
from django.test import TransactionTestCase

from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryAuditEvent, DeliveryAttempt, ProviderReceipt, ProviderSignatureEvidence
from apps.delivery_queue.signed_provider_receipts import (
    SignedProviderEvent, Ed25519ProviderEventVerifier,
    provider_signing_payload, record_signed_provider_event,
    verify_stored_provider_evidence,
)

A, B, C = "a" * 64, "b" * 64, "c" * 64


@unittest.skipUnless(connection.vendor == "postgresql", "owned PostgreSQL 17/18 only")
class SignedProviderReceiptsTests(TransactionTestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        )
        self.verifier = self.make_verifier()
        queue.commit_approved_plan(
            receipt_id="signed-provider-approval-1", nonce="N" * 40,
            approval_fingerprint=A, plan_fingerprint=C, case_key="test-provider-case",
            answer_revision=5, provider="reply-source",
            expires_at=self.now + timedelta(minutes=8),
            parts=((1, A), (2, B)), verify_approval=lambda: True,
        )

    def make_verifier(self, **values):
        settings = dict(
            issuer="synthetic-channel-test",
            audience="fatwa.delivery-receipt.v1",
            provider="reply-source",
            trusted_public_keys={"key-1": self.public},
            clock=lambda: self.now,
        )
        settings.update(values)
        return Ed25519ProviderEventVerifier(**settings)

    def lease(self):
        return queue.claim_next(provider="reply-source", worker_id="worker-test")

    def signed_event(self, lease, *, reported="DELIVERED", receipt_reference="signed-event-1", **changes):
        intent = queue.DeliveryIntent.objects.get(pk=lease.intent_key)
        fields = dict(
            issuer="synthetic-channel-test", audience="fatwa.delivery-receipt.v1",
            key_id="key-1", provider="reply-source", plan_fingerprint=intent.plan_fingerprint,
            intent_key=intent.pk, ordinal=intent.ordinal,
            part_digest=intent.payload_sha256, attempt_sha256=sha256(lease.token.encode()).hexdigest(),
            receipt_reference=receipt_reference, provider_message_id="provider-message-1",
            reported=reported, issued_at=(self.now - timedelta(seconds=1)).isoformat(),
            expires_at=(self.now + timedelta(minutes=5)).isoformat(),
            signature_b64url="",
        )
        fields.update(changes)
        unsigned = SignedProviderEvent(**fields)
        signature = base64.urlsafe_b64encode(
            self.private.sign(provider_signing_payload(unsigned))
        ).decode("ascii").rstrip("=")
        return replace(unsigned, signature_b64url=signature)

    def record(self, lease, event, verifier=None):
        return record_signed_provider_event(
            lease=lease, event=event, verifier=verifier or self.verifier,
        )

    def test_two_signed_delivered_parts_required_for_complete(self):
        first, second = self.lease(), self.lease()
        result = self.record(first, self.signed_event(first))
        self.assertFalse(result.complete)
        self.assertEqual((result.delivered_parts, result.state), (1, "PARTIALLY_DELIVERED"))
        result = self.record(second, self.signed_event(
            second, receipt_reference="signed-event-2", provider_message_id="provider-message-2",
        ))
        self.assertTrue(result.complete)
        self.assertEqual(result.state, "DELIVERED")
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 2)
        self.assertEqual(ProviderReceipt.objects.count(), 2)

    def test_accepted_never_means_delivered_and_new_proof_advances(self):
        first = self.lease()
        first_event = self.signed_event(first, reported="ACCEPTED", receipt_reference="event-accepted")
        result = self.record(first, first_event)
        self.assertFalse(result.complete)
        self.assertEqual(result.state, "IN_PROGRESS")
        result = self.record(first, self.signed_event(first, receipt_reference="event-delivered"))
        self.assertEqual(result.state, "PARTIALLY_DELIVERED")
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 2)

    def test_changed_signature_claim_is_rejected_without_mutating_queue(self):
        lease = self.lease()
        event = self.signed_event(lease, reported="ACCEPTED")
        with self.assertRaises(queue.QueueConflict):
            self.record(lease, replace(event, reported="DELIVERED"))
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(queue.DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")

    def test_wrong_target_provider_part_or_attempt_is_rejected(self):
        lease, other = self.lease(), self.lease()
        for changes in (
            {"intent_key": other.intent_key},
            {"ordinal": 2},
            {"part_digest": B},
            {"provider": "other-provider"},
            {"plan_fingerprint": B},
            {"attempt_sha256": B},
        ):
            with self.subTest(**changes), self.assertRaises(queue.QueueConflict):
                self.record(lease, self.signed_event(lease, **changes))
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_unknown_key_retired_key_wrong_issuer_and_audience_are_denied(self):
        lease = self.lease()
        event = self.signed_event(lease)
        for verifier in (
            self.make_verifier(trusted_public_keys={"other-key": self.public}),
            self.make_verifier(revoked_key_ids=frozenset({"key-1"})),
            self.make_verifier(issuer="other-issuer"),
            self.make_verifier(audience="other-audience"),
        ):
            with self.assertRaises(queue.QueueConflict):
                self.record(lease, event, verifier=verifier)
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_verifier_availability_failure_is_never_clearance(self):
        lease = self.lease()
        broken = self.make_verifier(
            is_key_revoked=lambda key_id: (_ for _ in ()).throw(RuntimeError("directory offline"))
        )
        with self.assertRaises(queue.QueueConflict):
            self.record(lease, self.signed_event(lease), verifier=broken)
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_expired_future_and_overlong_signed_proofs_fail_closed(self):
        lease = self.lease()
        for overrides in (
            {"expires_at": (self.now - timedelta(seconds=1)).isoformat()},
            {"issued_at": (self.now + timedelta(minutes=2)).isoformat()},
            {"expires_at": (self.now + timedelta(hours=2)).isoformat()},
        ):
            with self.subTest(**overrides), self.assertRaises(queue.QueueConflict):
                self.record(lease, self.signed_event(lease, **overrides))
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_exact_replay_is_idempotent_but_reusing_reference_for_new_event_fails(self):
        lease = self.lease()
        event = self.signed_event(lease, reported="ACCEPTED")
        self.record(lease, event)
        before = DeliveryAuditEvent.objects.count()
        self.record(lease, event)
        self.assertEqual(ProviderReceipt.objects.count(), 1)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 1)
        self.assertEqual(DeliveryAuditEvent.objects.count(), before)
        with self.assertRaises(queue.QueueConflict):
            self.record(lease, self.signed_event(lease, reported="DELIVERED"))
        self.assertEqual(DeliveryAuditEvent.objects.count(), before)

    def test_wrong_worker_token_cannot_replay_a_valid_provider_signature(self):
        lease = self.lease()
        event = self.signed_event(lease)
        with self.assertRaises(queue.QueueConflict):
            self.record(replace(lease, token="incorrect-token-00000000000000000000"), event)
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_late_signed_delivery_after_expiry_quarantine_is_preserved(self):
        lease = self.lease()
        event = self.signed_event(lease, receipt_reference="late-signed-receipt")
        queue.quarantine_expired_leases(now=lease.expires_at + timedelta(seconds=1))
        self.assertEqual(
            queue.DeliveryIntent.objects.get(pk=lease.intent_key).state,
            "UNKNOWN_REQUIRES_RECONCILIATION",
        )
        other = self.lease()
        self.assertIsNotNone(other)
        self.assertNotEqual(other.intent_key, lease.intent_key)
        result = self.record(lease, event)
        self.assertFalse(result.complete)
        self.assertEqual(result.state, "PARTIALLY_DELIVERED")

    def test_historical_proof_can_be_verified_without_fresh_delivery_or_secret(self):
        lease = self.lease()
        self.record(lease, self.signed_event(lease))
        stored = ProviderSignatureEvidence.objects.get()
        self.assertEqual(stored.receipt_id, "signed-event-1")
        self.assertNotIn(lease.token, str(stored.envelope))
        self.now += timedelta(hours=1)
        self.assertTrue(verify_stored_provider_evidence(
            receipt_reference="signed-event-1", verifier=self.verifier
        ))
        self.assertEqual(ProviderReceipt.objects.count(), 1)

    def test_signature_evidence_is_append_only_at_database_level(self):
        lease = self.lease()
        self.record(lease, self.signed_event(lease))
        with self.assertRaises(IntegrityError):
            ProviderSignatureEvidence.objects.update(envelope={"fake": True})
        with self.assertRaises(IntegrityError):
            ProviderSignatureEvidence.objects.all().delete()
        self.assertTrue(verify_stored_provider_evidence(
            receipt_reference="signed-event-1", verifier=self.verifier
        ))

    def test_crash_during_audit_write_rolls_back_signed_receipt_and_intent(self):
        lease = self.lease()
        event = self.signed_event(lease)
        with patch.object(queue, "_audit", side_effect=RuntimeError("synthetic-crash")):
            with self.assertRaisesRegex(RuntimeError, "synthetic-crash"):
                self.record(lease, event)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.assertEqual(queue.DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")
        self.record(lease, event)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 1)

    def test_verified_provider_audit_requires_all_parts(self):
        from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
        first, second = self.lease(), self.lease()
        self.record(first, self.signed_event(first))
        audit = audit_provider_reported_delivery(plan_fingerprint=C, verifier=self.verifier)
        self.assertFalse(audit.cryptographically_verified_complete)
        self.assertFalse(audit.provider_reported_complete)
        self.assertEqual(audit.verified_delivered_parts, 1)
        self.record(second, self.signed_event(second,
            receipt_reference="signed-second", provider_message_id="second-message"))
        audit = audit_provider_reported_delivery(plan_fingerprint=C, verifier=self.verifier)
        self.assertTrue(audit.provider_reported_complete)
        self.assertTrue(audit.cryptographically_verified_complete)
        self.assertEqual(audit.verified_delivered_parts, 2)
        self.assertEqual(audit.unverified_delivered_parts, 0)

    def test_legacy_boolean_receipts_are_not_cryptographic_provider_evidence(self):
        from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
        first, second = self.lease(), self.lease()
        for i, lease in enumerate((first, second), 1):
            queue.record_receipt(
                lease=lease, receipt_reference=f"legacy-receipt-{i}",
                provider_message_id=f"legacy-message-{i}", reported="DELIVERED",
                verify_provider_receipt=lambda proof: True,
            )
        self.assertTrue(queue.summarize_plan(C).complete)
        audit = audit_provider_reported_delivery(plan_fingerprint=C, verifier=self.verifier)
        self.assertTrue(audit.provider_reported_complete)
        self.assertFalse(audit.cryptographically_verified_complete)
        self.assertEqual(audit.unverified_delivered_parts, 2)
        self.assertEqual(audit.status, "PROVIDER_EVIDENCE_INCOMPLETE")

    def test_revoked_provider_key_invalidates_verified_completeness(self):
        from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
        first, second = self.lease(), self.lease()
        self.record(first, self.signed_event(first))
        self.record(second, self.signed_event(second,
            receipt_reference="proof-two", provider_message_id="message-two"))
        disabled = self.make_verifier(revoked_key_ids=frozenset({"key-1"}))
        audit = audit_provider_reported_delivery(plan_fingerprint=C, verifier=disabled)
        self.assertTrue(audit.provider_reported_complete)
        self.assertFalse(audit.cryptographically_verified_complete)
        self.assertEqual(audit.unverified_delivered_parts, 2)

    def test_provider_evidence_audit_is_read_only_and_no_secret_in_summary(self):
        from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
        lease = self.lease()
        self.record(lease, self.signed_event(lease))
        before = list(DeliveryAuditEvent.objects.values_list("sequence", "digest"))
        audit = audit_provider_reported_delivery(plan_fingerprint=C, verifier=self.verifier)
        self.assertEqual(before, list(DeliveryAuditEvent.objects.values_list("sequence", "digest")))
        self.assertNotIn(lease.token, str(audit))
        self.assertNotIn("signature_b64url", str(audit))

    def test_provider_evidence_audit_fails_closed_on_unknown_plan_or_verifier(self):
        from apps.delivery_queue.signed_provider_receipts import audit_provider_reported_delivery
        with self.assertRaises(queue.QueueConflict):
            audit_provider_reported_delivery(plan_fingerprint="e" * 64, verifier=self.verifier)
        with self.assertRaises(queue.QueueConflict):
            audit_provider_reported_delivery(plan_fingerprint=C, verifier=lambda event: True)
