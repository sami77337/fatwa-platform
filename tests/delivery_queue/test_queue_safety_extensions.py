"""Real PostgreSQL races, process isolation and database-level negative cases."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import importlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.db import connection, connections, close_old_connections, IntegrityError
from django.test import TransactionTestCase
from django.utils import timezone
from apps.delivery_queue import services as q
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt, DeliveryAuditEvent, DeliveryIntent, ProviderReceipt

A, B, C = 'a' * 64, 'b' * 64, 'c' * 64


class QueueSafetyExtensions(TransactionTestCase):
    def stage(self, parts=((1, B),)):
        return q.commit_approved_plan(receipt_id='extended-receipt', nonce='Z' * 40,
            approval_fingerprint=A, plan_fingerprint=C, case_key='extended-case',
            answer_revision=1, provider='reply-source', expires_at=timezone.now() + timedelta(minutes=5),
            parts=parts, verify_approval=lambda: True)

    def concurrent(self, *functions):
        barrier = Barrier(len(functions), timeout=10)
        def run(function):
            close_old_connections()
            try:
                barrier.wait()
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(run, function) for function in functions]
            return [future.result(timeout=20) for future in futures]

    def test_database_rejects_a_null_token_in_leased_state(self):
        self.stage()
        with self.assertRaises(IntegrityError):
            DeliveryIntent.objects.update(state='LEASED', lease_owner='worker-1',
                lease_expires_at=timezone.now() + timedelta(seconds=20), lease_token_sha256=None)

    def test_database_rejects_a_null_provider_status_in_delivered_state(self):
        self.stage()
        with self.assertRaises(IntegrityError):
            DeliveryIntent.objects.update(state='DELIVERED', provider_message_id='message-1', provider_status=None)

    def test_two_independent_processes_cannot_claim_the_same_intent(self):
        self.stage()
        database_name = connection.settings_dict['NAME']
        root = Path(__file__).resolve().parents[2]
        def process(worker):
            result = subprocess.run([sys.executable, '-m', 'tests.delivery_queue.worker_probe',
                database_name, worker], cwd=root, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)['intent_key']
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(process, ('process-worker-a', 'process-worker-b')))
        self.assertEqual(sum(value is not None for value in values), 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.assertEqual(DeliveryAuditEvent.objects.filter(new_state='LEASED').count(), 1)
        self.assertEqual(q.verify_audit_chain()[0], 2)

    def test_concurrent_duplicate_provider_event_has_one_durable_result(self):
        self.stage()
        lease = q.claim_next(provider='reply-source', worker_id='worker-a')
        def record():
            return q.record_receipt(lease=lease, receipt_reference='concurrent-event',
                provider_message_id='message-1', reported='DELIVERED',
                verify_provider_receipt=lambda proof: True).state
        states = self.concurrent(record, record)
        self.assertEqual(states, ['DELIVERED', 'DELIVERED'])
        self.assertEqual(ProviderReceipt.objects.count(), 1)
        self.assertEqual(DeliveryAuditEvent.objects.filter(new_state='DELIVERED').count(), 1)
        self.assertTrue(q.summarize_plan(C).complete)

    def test_late_delivery_and_expiry_quarantine_race_preserve_delivery(self):
        self.stage()
        lease = q.claim_next(provider='reply-source', worker_id='worker-a')
        def deliver():
            return q.record_receipt(lease=lease, receipt_reference='late-race-event',
                provider_message_id='message-1', reported='DELIVERED',
                verify_provider_receipt=lambda proof: True).state
        def quarantine():
            return q.quarantine_expired_leases(now=lease.expires_at + timedelta(seconds=1))
        self.concurrent(deliver, quarantine)
        self.assertEqual(DeliveryIntent.objects.get().state, 'DELIVERED')
        self.assertTrue(q.summarize_plan(C).complete)

    def test_audit_read_is_consistent_while_other_connections_claim(self):
        self.stage(parts=((1, B), (2, A)))
        def claim():
            return q.claim_next(provider='reply-source', worker_id='worker-a')
        def audit():
            return [q.verify_audit_chain() for _ in range(4)]
        self.concurrent(claim, audit)
        self.assertEqual(q.verify_audit_chain()[0], 3)

    def test_attempt_and_state_roll_back_together_when_audit_fails(self):
        self.stage()
        with patch.object(q, '_audit', side_effect=RuntimeError('injected-audit-failure')):
            with self.assertRaisesRegex(RuntimeError, 'injected-audit-failure'):
                q.claim_next(provider='reply-source', worker_id='worker-a')
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.get().state, 'STAGED')
        self.assertEqual(q.verify_audit_chain()[0], 1)

    def test_new_metadata_migration_refuses_existing_delivery_rows(self):
        self.stage()
        migration = importlib.import_module('apps.delivery_queue.migrations.0003_signed_context_and_attempt')
        with self.assertRaisesRegex(RuntimeError, 'separately approved migration'):
            migration.require_empty_queue(apps, SimpleNamespace(connection=connection))
        self.assertEqual(ApprovalClaim.objects.count(), 1)
