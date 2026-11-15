"""External HMAC audit checkpoints bind a trusted key to the current Outbox tip."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.audit_attestation import (
    create_audit_attestation, verify_audit_attestation,
)
from apps.delivery_planner.outbox import FILE_NAME, list_intents, reserve_for_adapter, stage_plan
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery

A, B, C = "a" * 64, "b" * 64, "c" * 64
KEY = b"test-only-external-checkpoint-key-32-bytes-minimum!!"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class ExternalAuditAttestationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        evidence = CurrentEvidence("case-attest-1", 2, A, B, "")
        self.evidence = evidence
        approval = ApprovalReceipt(
            "case-attest-1", 2, A, B, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "attest-approval-1", NOW.isoformat(),
        )
        self.approval = approval
        plan = plan_delivery(
            case_key="case-attest-1", source_peer_key="thread:attest-1",
            parts=(Part(1, "text", C, 25),),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 100, True),
            authority=Authority(2, A, True), choice=Choice(),
        )
        self.plan = plan
        self.verify = lambda item: item == approval
        stage_plan(
            self.directory, plan=plan, approval=approval, evidence=evidence,
            verify_approval=self.verify, synthetic_fixtures_only=True,
        )

    def attest(self, key_id="audit-key-1", key=KEY):
        return create_audit_attestation(
            self.directory, key_id=key_id, signing_key=key, created_at=NOW,
        )

    def test_valid_external_checkpoint_matches_current_audit_head(self):
        proof = self.attest()
        self.assertTrue(verify_audit_attestation(
            self.directory, attestation=proof, trusted_keys={"audit-key-1": KEY},
        ))

    def test_unknown_wrong_or_short_key_fails_closed(self):
        proof = self.attest()
        self.assertFalse(verify_audit_attestation(
            self.directory, attestation=proof, trusted_keys={},
        ))
        self.assertFalse(verify_audit_attestation(
            self.directory, attestation=proof,
            trusted_keys={"audit-key-1": b"x" * 32},
        ))
        with self.assertRaisesRegex(ValueError, "audit_attestation_key_invalid"):
            self.attest(key=b"short")

    def test_claim_tampering_and_signature_tampering_are_rejected(self):
        proof = self.attest()
        for changed in (
            replace(proof, sequence=proof.sequence + 1),
            replace(proof, head_digest="f" * 64),
            replace(proof, key_id="other-key"),
            replace(proof, signature_hmac_sha256="0" * 64),
            replace(proof, database_version=3),
        ):
            self.assertFalse(verify_audit_attestation(
                self.directory, attestation=changed,
                trusted_keys={"audit-key-1": KEY},
            ))

    def test_external_checkpoint_detects_rebuilt_local_hash_chain(self):
        proof = self.attest()
        with sqlite3.connect(self.directory / FILE_NAME) as con:
            con.execute("DROP TRIGGER immutable_outbox_events_update")
            con.execute("DROP TRIGGER immutable_outbox_events_delete")
            con.execute(
                "UPDATE events SET evidence_ref='operator:rewritten' WHERE seq=1"
            )
            rows = con.execute(
                "SELECT seq,intent_key,old_state,new_state,evidence_ref,recorded_at "
                "FROM events ORDER BY seq"
            ).fetchall()
            con.execute("DELETE FROM events")
            from hashlib import sha256
            import json
            previous = ""
            for row in rows:
                seq, key, old, new, ref, recorded = row
                payload = [seq, key, old, new, ref, recorded]
                digest = sha256((previous + json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                )).encode()).hexdigest()
                con.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                    (seq, key, old, new, ref, recorded, previous, digest),
                )
                previous = digest
            con.execute("UPDATE audit_head SET digest=? WHERE id=1", (previous,))
            con.commit()
        # Local hash-chain validation still succeeds, but the external HMAC
        # checkpoint binds the old tip and therefore detects the rewrite.
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 1)
        self.assertFalse(verify_audit_attestation(
            self.directory, attestation=proof, trusted_keys={"audit-key-1": KEY},
        ))

    def test_new_audit_event_invalidates_old_checkpoint_and_new_one_verifies(self):
        old = self.attest()
        row, = list_intents(self.directory, synthetic_fixtures_only=True)
        reserve_for_adapter(
            self.directory, intent_key=row.intent_key, plan=self.plan,
            approval=self.approval, evidence=self.evidence,
            verify_approval=self.verify,
            get_current_evidence=lambda case: self.evidence,
            synthetic_fixtures_only=True,
        )
        self.assertFalse(verify_audit_attestation(
            self.directory, attestation=old, trusted_keys={"audit-key-1": KEY},
        ))
        fresh = self.attest()
        self.assertTrue(verify_audit_attestation(
            self.directory, attestation=fresh, trusted_keys={"audit-key-1": KEY},
        ))

    def test_key_rotation_uses_explicit_key_ids_without_accepting_retired_key(self):
        old = self.attest("audit-key-old", KEY)
        new_key = b"rotated-external-key-32-bytes-for-tests-only!!"
        new = self.attest("audit-key-new", new_key)
        self.assertTrue(verify_audit_attestation(
            self.directory, attestation=old,
            trusted_keys={"audit-key-old": KEY, "audit-key-new": new_key},
        ))
        self.assertTrue(verify_audit_attestation(
            self.directory, attestation=new,
            trusted_keys={"audit-key-new": new_key},
        ))
        self.assertFalse(verify_audit_attestation(
            self.directory, attestation=old,
            trusted_keys={"audit-key-new": new_key},
        ))


if __name__ == "__main__":
    unittest.main()
