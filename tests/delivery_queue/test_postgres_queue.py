"""PostgreSQL-only integration tests for atomic approvals and concurrent workers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from threading import Barrier
import unittest

from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent, ProviderReceipt
from apps.delivery_queue.services import (
    QueueConflict, claim_next, commit_approved_plan, quarantine_expired_leases,
    record_receipt, summarize_plan,
)

A, B, C = "a"*64, "b"*64, "c"*64


@unittest.skipUnless(connection.vendor == "postgresql", "requires PostgreSQL 17/18")
class PostgreSQLDeliveryQueueTests(TransactionTestCase):
    reset_sequences = True

    def commit(self, *, receipt_id="pg-approval-1", plan=C, nonce="N"*40, parts=None):
        return commit_approved_plan(
            receipt_id=receipt_id, nonce=nonce, approval_fingerprint=A,
            plan_fingerprint=plan, case_key="pg-case-1", answer_revision=3,
            provider="reply-source", expires_at=timezone.now()+timedelta(minutes=5),
            parts=parts or ((1,B),(2,C)), verify_approval=lambda: True,
        )

    def test_approval_is_consumed_once_and_exact_replay_is_idempotent(self):
        first=self.commit()
        second=self.commit()
        self.assertEqual([x.intent_key for x in first],[x.intent_key for x in second])
        self.assertEqual(ApprovalClaim.objects.count(),1)
        self.assertEqual(DeliveryIntent.objects.count(),2)
        with self.assertRaisesRegex(QueueConflict,"approval_receipt_already_consumed"):
            self.commit(plan="d"*64)

    def test_nonce_cannot_be_reused_by_another_receipt(self):
        self.commit()
        with self.assertRaisesRegex(QueueConflict,"approval_nonce_already_consumed"):
            self.commit(receipt_id="pg-approval-2", plan="d"*64)

    def test_two_workers_claim_distinct_rows_with_skip_locked(self):
        self.commit()
        barrier=Barrier(2)
        def worker(worker_id):
            close_old_connections()
            try:
                barrier.wait()
                lease=claim_next(provider="reply-source",worker_id=worker_id)
                return lease.intent_key if lease else None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(worker,("worker-a","worker-b")))
        self.assertEqual(len(set(results)),2)
        self.assertNotIn(None,results)

    def test_receipt_and_audit_commit_atomically_and_exact_replay_is_safe(self):
        self.commit(parts=((1,B),))
        lease=claim_next(provider="reply-source",worker_id="worker-a")
        result=record_receipt(
            lease=lease,receipt_reference="provider-event-1",
            provider_message_id="provider-message-1",reported="DELIVERED",
            verify_provider_receipt=lambda proof: True,
        )
        replay=record_receipt(
            lease=lease,receipt_reference="provider-event-1",
            provider_message_id="provider-message-1",reported="DELIVERED",
            verify_provider_receipt=lambda proof: True,
        )
        self.assertEqual(result.state,DeliveryIntent.DELIVERED)
        self.assertEqual(replay.state,DeliveryIntent.DELIVERED)
        self.assertEqual(ProviderReceipt.objects.count(),1)
        self.assertEqual(summarize_plan(C).state,"DELIVERED")
        self.assertTrue(summarize_plan(C).complete)

    def test_accepted_receipt_can_advance_to_delivered_with_a_new_event(self):
        self.commit(parts=((1,B),))
        lease=claim_next(provider="reply-source",worker_id="worker-a")
        accepted=record_receipt(
            lease=lease,receipt_reference="provider-event-accepted",
            provider_message_id="provider-message-progress",reported="ACCEPTED",
            verify_provider_receipt=lambda proof: True,
        )
        self.assertEqual(accepted.state,DeliveryIntent.SENT_UNCONFIRMED)
        delivered=record_receipt(
            lease=lease,receipt_reference="provider-event-delivered",
            provider_message_id="provider-message-progress",reported="DELIVERED",
            verify_provider_receipt=lambda proof: True,
        )
        self.assertEqual(delivered.state,DeliveryIntent.DELIVERED)
        self.assertEqual(ProviderReceipt.objects.count(),2)
        self.assertTrue(summarize_plan(C).complete)

    def test_changed_receipt_payload_is_rejected(self):
        self.commit(parts=((1,B),))
        lease=claim_next(provider="reply-source",worker_id="worker-a")
        record_receipt(
            lease=lease,receipt_reference="provider-event-2",
            provider_message_id="provider-message-1",reported="ACCEPTED",
            verify_provider_receipt=lambda proof: True,
        )
        with self.assertRaisesRegex(QueueConflict,"provider_receipt_reference_reused"):
            record_receipt(
                lease=lease,receipt_reference="provider-event-2",
                provider_message_id="provider-message-1",reported="DELIVERED",
                verify_provider_receipt=lambda proof: True,
            )

    def test_late_verified_receipt_reconciles_quarantined_attempt_without_requeue(self):
        self.commit(parts=((1,B),))
        lease=claim_next(provider="reply-source",worker_id="worker-a",lease_seconds=1)
        quarantine_expired_leases(now=lease.expires_at+timedelta(seconds=1))
        result=record_receipt(
            lease=lease,receipt_reference="late-provider-event",
            provider_message_id="late-provider-message",reported="DELIVERED",
            verify_provider_receipt=lambda proof: True,
        )
        self.assertEqual(result.state,DeliveryIntent.DELIVERED)
        self.assertTrue(summarize_plan(C).complete)

    def test_expired_worker_lease_is_quarantined_not_requeued(self):
        self.commit(parts=((1,B),))
        lease=claim_next(provider="reply-source",worker_id="worker-a",lease_seconds=1)
        changed=quarantine_expired_leases(now=lease.expires_at+timedelta(seconds=1))
        self.assertEqual(changed,(lease.intent_key,))
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state,
                         DeliveryIntent.UNKNOWN_REQUIRES_RECONCILIATION)
        self.assertIsNone(claim_next(provider="reply-source",worker_id="worker-b"))


if __name__ == "__main__":
    unittest.main()
