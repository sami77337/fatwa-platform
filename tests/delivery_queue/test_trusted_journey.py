"""Signed approval, fresh evidence and exact Arabic text through PostgreSQL."""
from base64 import urlsafe_b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import inspect
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from django.db import connection, IntegrityError
from django.test import TransactionTestCase
from apps.delivery_planner.approval import CurrentEvidence
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery
from apps.delivery_planner.segmentation import parts_for_delivery, SegmentationNeedsReview
from apps.delivery_planner.trusted_identity import (
    SignedApprovalReceipt, Ed25519ApprovalVerifier, IdentityStatus,
    approval_signing_payload, canonical_plan_sha256,
)
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as q
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt, DeliveryIntent, SignedDeliveryContext


class TrustedJourneyTests(TransactionTestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.private = Ed25519PrivateKey.generate()
        self.active = True
        self.revoked = False
        self.title = 'جواب محفوظ'
        self.body = 'نصّ عربي محفوظ كما هو.\r\n  فقرة ثانية دون حذف أو إعادة صياغة.  '
        content = json.dumps(['human-answer-content.v1', self.title, self.body],
                             ensure_ascii=False, separators=(',', ':')).encode()
        self.evidence = CurrentEvidence('trusted-case', 2, sha256(content).hexdigest(), 'b' * 64, '')
        self.caps = Capabilities('reply-source', 'v1', frozenset({'text'}), 32, True)
        self.parts, self.segments = parts_for_delivery(self.body, self.caps, explicit_human_choice=True)
        self.plan = plan_delivery(case_key=self.evidence.case_key, source_peer_key='thread:trusted',
            parts=self.parts, capabilities=self.caps,
            authority=Authority(2, self.evidence.answer_sha256, True), choice=Choice())
        self.receipt = self.sign(self.plan)
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.verifier = Ed25519ApprovalVerifier(issuer='identity.test', audience='fatwa.return',
            trusted_public_keys={'key-1': public},
            identity_lookup=lambda subject: IdentityStatus('mufti-1', 'MUFTI', self.active),
            is_revoked_or_consumed=lambda *args: self.revoked,
            clock=lambda: self.now)

    def api(self, name):
        result = getattr(adapter, name, None)
        self.assertTrue(callable(result), name + ' must be implemented')
        return result

    def sign(self, plan):
        r = SignedApprovalReceipt(case_key=self.evidence.case_key, answer_revision=2,
            answer_sha256=self.evidence.answer_sha256, source_digest=self.evidence.source_digest,
            reply_digest='', approver_id='mufti-1', approver_role='MUFTI',
            decision='APPROVE_RETURN_TO_ORIGIN', receipt_id='trusted-receipt',
            issued_at=(self.now - timedelta(seconds=1)).isoformat(), issuer='identity.test',
            audience='fatwa.return', key_id='key-1', expires_at=(self.now + timedelta(minutes=4)).isoformat(),
            nonce='N' * 43, plan_sha256=canonical_plan_sha256(plan), signature_b64url='')
        return replace(r, signature_b64url=urlsafe_b64encode(self.private.sign(approval_signing_payload(r))).decode().rstrip('='))

    def commit(self, **changes):
        kwargs = dict(receipt=self.receipt, evidence=self.evidence, plan=self.plan, verify_receipt=self.verifier)
        kwargs.update(changes)
        return adapter.commit_signed_approved_plan(**kwargs)

    def reserve(self, **changes):
        kwargs = dict(plan_fingerprint=canonical_plan_sha256(self.plan), worker_id='worker-trusted',
            verify_worker=lambda worker, plan: worker == 'worker-trusted',
            verify_receipt=self.verifier, read_current_evidence=lambda case: self.evidence)
        kwargs.update(changes)
        return self.api('reserve_signed_plan')(**kwargs)

    def prepare(self, **changes):
        kwargs = dict(title=self.title, body=self.body, evidence=self.evidence,
            source_peer_key='thread:trusted', capabilities=self.caps, explicit_human_choice=True)
        kwargs.update(changes)
        return self.api('prepare_text_return')(**kwargs)

    def test_signed_metadata_is_persisted_once_without_answer_body(self):
        self.commit()
        self.commit()
        self.assertEqual(SignedDeliveryContext.objects.count(), 1)
        saved = SignedDeliveryContext.objects.get()
        self.assertNotIn(self.body, json.dumps(saved.envelope, ensure_ascii=False))
        self.assertNotIn('PRIVATE KEY', json.dumps(saved.envelope))
        with self.assertRaises(IntegrityError):
            SignedDeliveryContext.objects.filter(pk=saved.pk).update(envelope={})

    def test_current_evidence_is_rechecked_inside_the_locked_commit(self):
        self.assertIn('read_current_evidence', inspect.signature(adapter.commit_signed_approved_plan).parameters)
        seen = []
        def current(case):
            seen.append(connection.in_atomic_block)
            return self.evidence
        self.commit(read_current_evidence=current)
        self.assertTrue(seen)
        self.assertTrue(all(seen))

    def test_changed_source_before_commit_creates_no_claim(self):
        self.assertIn('read_current_evidence', inspect.signature(adapter.commit_signed_approved_plan).parameters)
        with self.assertRaises(ValueError):
            self.commit(read_current_evidence=lambda case: replace(self.evidence, source_digest='c' * 64))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_non_sending_human_decision_plan_is_not_staged_as_sendable(self):
        held = plan_delivery(case_key='trusted-case', source_peer_key='thread:trusted',
            parts=(Part(1, 'video', 'c' * 64, 50),), capabilities=self.caps,
            authority=Authority(2, self.evidence.answer_sha256, True), choice=Choice())
        with self.assertRaises(ValueError):
            self.commit(receipt=self.sign(held), plan=held)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_unsigned_verifier_boolean_is_not_a_trusted_identity_adapter(self):
        with self.assertRaises(ValueError):
            self.commit(verify_receipt=lambda receipt: True)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_signed_plan_cannot_use_unverified_low_level_worker_claim(self):
        self.commit()
        with self.assertRaises(q.QueueConflict):
            q.claim_next(provider='reply-source', worker_id='worker-trusted')
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_revocation_after_staging_blocks_reservation(self):
        self.commit()
        self.revoked = True
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_source_change_after_staging_blocks_reservation(self):
        self.commit()
        with self.assertRaises(ValueError):
            self.reserve(read_current_evidence=lambda case: replace(self.evidence, clarification_pending=True))
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_worker_authorization_is_required(self):
        self.commit()
        with self.assertRaises(ValueError):
            self.reserve(verify_worker=lambda worker, plan: False)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_unavailable_evidence_reader_does_not_allocate_a_lease(self):
        self.commit()
        def unavailable(case):
            raise OSError('reader unavailable')
        with self.assertRaises(ValueError):
            self.reserve(read_current_evidence=unavailable)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_exact_arabic_text_and_crlf_survive_preparation(self):
        prepared = self.prepare()
        self.assertEqual(''.join(s.exact_text for s in prepared.segments), self.body)
        self.assertEqual(canonical_plan_sha256(prepared.plan), canonical_plan_sha256(self.plan))

    def test_text_changed_without_new_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(body=self.body + 'زيادة')

    def test_text_split_requires_an_explicit_human_choice(self):
        self.api('prepare_text_return')
        with self.assertRaises(SegmentationNeedsReview):
            self.prepare(explicit_human_choice=False)

    def test_reserved_part_is_exact_and_no_text_is_written_to_queue(self):
        prepared = self.prepare()
        self.commit()
        lease = self.reserve()
        segment = self.api('resolve_reserved_text')(lease=lease, prepared=prepared,
            verify_receipt=self.verifier, read_current_evidence=lambda case: self.evidence)
        intent = DeliveryIntent.objects.get(pk=lease.intent_key)
        self.assertEqual(segment.exact_text, self.segments[intent.ordinal - 1].exact_text)
        self.assertNotIn(self.body, str(list(DeliveryIntent.objects.values())))

    def test_payload_resolution_rechecks_revocation_after_reservation(self):
        prepared = self.prepare()
        self.commit()
        lease = self.reserve()
        self.revoked = True
        with self.assertRaises(ValueError):
            self.api('resolve_reserved_text')(lease=lease, prepared=prepared,
                verify_receipt=self.verifier, read_current_evidence=lambda case: self.evidence)

    def test_all_parts_need_independent_delivery_proofs(self):
        self.commit()
        leases = []
        for _ in self.parts:
            leases.append(self.reserve())
        self.assertEqual(len({lease.intent_key for lease in leases}), len(self.parts))
        for index, lease in enumerate(leases):
            q.record_receipt(lease=lease, receipt_reference='event-' + str(index),
                provider_message_id='message-' + str(index), reported='DELIVERED',
                verify_provider_receipt=lambda proof: True)
            self.assertEqual(q.summarize_plan(canonical_plan_sha256(self.plan)).complete,
                             index == len(leases) - 1)
        self.assertIsNone(self.reserve())
