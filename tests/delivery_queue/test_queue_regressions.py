"""Regression boundaries for the existing real PostgreSQL queue."""
from dataclasses import replace
from datetime import timedelta
import os
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.delivery_queue import services as q
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent, ProviderReceipt

A, B, C = 'a' * 64, 'b' * 64, 'c' * 64


class QueueBoundaryRegressions(TransactionTestCase):
    def stage(self, **overrides):
        values = dict(receipt_id='regression-approval', nonce='R' * 40,
            approval_fingerprint=A, plan_fingerprint=C, case_key='regression-case',
            answer_revision=1, provider='reply-source',
            expires_at=timezone.now() + timedelta(minutes=5),
            parts=((1, B),), verify_approval=lambda: True)
        values.update(overrides)
        return q.commit_approved_plan(**values)

    def test_production_guard_rejects_before_any_database_query(self):
        with patch.dict(os.environ, {'FATWA_PRODUCTION': '1'}):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(q.QueueConflict):
                    q.claim_next(provider='reply-source', worker_id='worker-1')
            self.assertEqual(len(queries), 0)

    def test_disabled_synthetic_writes_reject_before_any_database_query(self):
        with patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_WRITES': '0'}):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(q.QueueConflict):
                    q.claim_next(provider='reply-source', worker_id='worker-1')
            self.assertEqual(len(queries), 0)

    def test_boolean_lease_duration_is_not_an_integer_policy(self):
        self.stage()
        with self.assertRaises(q.QueueConflict):
            q.claim_next(provider='reply-source', worker_id='worker-1', lease_seconds=True)
        self.assertEqual(DeliveryIntent.objects.get().state, 'STAGED')

    def test_expired_authorization_never_allocates_a_worker_lease(self):
        self.stage(expires_at=timezone.now() + timedelta(seconds=1))
        future = timezone.now() + timedelta(minutes=1)
        with patch.object(q.timezone, 'now', return_value=future):
            self.assertIsNone(q.claim_next(provider='reply-source', worker_id='worker-1'))
        self.assertEqual(DeliveryIntent.objects.get().state, 'STAGED')

    def test_approval_is_verified_after_transaction_lock(self):
        seen = []
        def verify():
            seen.append(connection.in_atomic_block)
            return connection.in_atomic_block
        self.stage(verify_approval=verify)
        self.assertTrue(seen)
        self.assertTrue(all(seen))

    def test_accepted_message_is_in_progress_not_staged(self):
        self.stage()
        lease = q.claim_next(provider='reply-source', worker_id='worker-1')
        q.record_receipt(lease=lease, receipt_reference='accepted-event',
            provider_message_id='message-1', reported='ACCEPTED',
            verify_provider_receipt=lambda proof: True)
        self.assertEqual(q.summarize_plan(C).state, 'IN_PROGRESS')
        self.assertFalse(q.summarize_plan(C).complete)

    def test_delivered_receipt_replay_requires_original_lease_token(self):
        self.stage()
        lease = q.claim_next(provider='reply-source', worker_id='worker-1')
        kwargs = dict(receipt_reference='delivered-event', provider_message_id='message-1',
            reported='DELIVERED', verify_provider_receipt=lambda proof: True)
        q.record_receipt(lease=lease, **kwargs)
        with self.assertRaises(q.QueueConflict):
            q.record_receipt(lease=replace(lease, token='wrong-token'), **kwargs)
        self.assertEqual(ProviderReceipt.objects.count(), 1)

    def test_boolean_part_ordinal_is_rejected_without_writes(self):
        with self.assertRaises(q.QueueConflict):
            self.stage(parts=((True, B),))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_malformed_values_have_fixed_errors_not_type_errors(self):
        for change in ({'receipt_id': None}, {'expires_at': None}, {'parts': (None,)},
                       {'nonce': 'x' * 200}, {'provider': 'x' * 65}):
            with self.subTest(change=change), self.assertRaises(q.QueueConflict):
                self.stage(**change)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
