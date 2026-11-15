"""External HMAC checkpoints protect the PostgreSQL delivery audit chain."""
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
import unittest

from django.db import connection
from django.test import TransactionTestCase

from apps.delivery_queue.audit_attestation import (
    create_postgres_audit_attestation, verify_postgres_audit_attestation,
)
from apps.delivery_queue.models import DeliveryAuditEvent, DeliveryAuditHead
from apps.delivery_queue.services import (
    claim_next, commit_approved_plan, verify_audit_chain,
)

A, B, C = "a"*64, "b"*64, "c"*64
KEY = b"test-only-postgres-audit-key-32-bytes-minimum!!"
NOW = datetime(2026, 11, 15, 12, 30, tzinfo=UTC)


@unittest.skipUnless(connection.vendor == "postgresql", "requires PostgreSQL 17/18")
class PostgresAuditAttestationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.commit_plan()
        self.proof = self.attest()

    def commit_plan(self):
        return commit_approved_plan(
            receipt_id="audit-pg-approval-1", nonce="P"*43,
            approval_fingerprint=A, plan_fingerprint=C,
            case_key="audit-pg-case", answer_revision=2,
            provider="reply-source", expires_at=NOW.replace(year=2027),
            parts=((1,B),), verify_approval=lambda: True,
        )

    def attest(self, key_id="pg-audit-key-1", key=KEY):
        return create_postgres_audit_attestation(
            key_id=key_id, signing_key=key, created_at=NOW,
        )

    def test_hash_chain_and_external_checkpoint_verify_current_head(self):
        self.assertEqual(verify_audit_chain()[0], 1)
        self.assertTrue(verify_postgres_audit_attestation(
            attestation=self.proof, trusted_keys={"pg-audit-key-1": KEY},
        ))

    def test_unknown_wrong_or_tampered_key_and_claims_fail_closed(self):
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=self.proof, trusted_keys={},
        ))
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=self.proof, trusted_keys={"pg-audit-key-1": b"x"*32},
        ))
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=replace(self.proof, sequence=9),
            trusted_keys={"pg-audit-key-1": KEY},
        ))

    def test_new_audit_event_invalidates_old_checkpoint(self):
        self.commit_plan()
        lease = claim_next(provider="reply-source", worker_id="audit-worker")
        self.assertIsNotNone(lease)
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=self.proof, trusted_keys={"pg-audit-key-1": KEY},
        ))
        fresh = self.attest()
        self.assertTrue(verify_postgres_audit_attestation(
            attestation=fresh, trusted_keys={"pg-audit-key-1": KEY},
        ))

    def test_rebuilt_local_hash_chain_is_rejected_by_external_checkpoint(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER fatwa_delivery_audit_immutable ON public.fatwa_delivery_audit_event")
        event = DeliveryAuditEvent.objects.order_by("sequence").first()
        DeliveryAuditEvent.objects.filter(pk=event.pk).update(event_reference="operator:rewritten")
        previous = ""
        rows = list(DeliveryAuditEvent.objects.order_by("sequence"))
        for row in rows:
            payload = [
                row.sequence, row.intent_id, row.old_state, row.new_state,
                row.event_reference, row.event_payload_sha256,
                row.recorded_at.isoformat(timespec="microseconds"),
            ]
            digest = sha256((previous + json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )).encode()).hexdigest()
            DeliveryAuditEvent.objects.filter(pk=row.pk).update(
                previous_digest=previous, digest=digest
            )
            previous = digest
        DeliveryAuditHead.objects.filter(pk=1).update(sequence=len(rows), digest=previous)
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TRIGGER fatwa_delivery_audit_immutable
                BEFORE UPDATE OR DELETE ON public.fatwa_delivery_audit_event
                FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows()
            """)
        self.assertEqual(verify_audit_chain()[0], 1)
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=self.proof, trusted_keys={"pg-audit-key-1": KEY},
        ))

    def test_key_rotation_rejects_retired_key(self):
        old = self.attest("pg-audit-old", KEY)
        new_key = b"rotated-postgres-audit-key-32-bytes-for-tests!!"
        new = self.attest("pg-audit-new", new_key)
        self.assertTrue(verify_postgres_audit_attestation(
            attestation=old, trusted_keys={"pg-audit-old": KEY, "pg-audit-new": new_key},
        ))
        self.assertTrue(verify_postgres_audit_attestation(
            attestation=new, trusted_keys={"pg-audit-new": new_key},
        ))
        self.assertFalse(verify_postgres_audit_attestation(
            attestation=old, trusted_keys={"pg-audit-new": new_key},
        ))


if __name__ == "__main__":
    unittest.main()
