"""Crash-boundary and late-receipt races preserve atomic outbox state."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
import unittest

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    ProviderReceipt, list_intents, record_provider_receipt,
    reserve_for_adapter, stage_plan,
)
from apps.delivery_planner.outbox_recovery import (
    flag_expired_reservations, plan_delivery_summaries,
)
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery

A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


class OutboxCrashConsistencyTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.evidence = CurrentEvidence("case-crash-1", 9, A, B, "")
        self.approval = ApprovalReceipt(
            "case-crash-1", 9, A, B, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "crash-approval-1",
            datetime.now(UTC).isoformat(),
        )
        self.verify = lambda value: value == self.approval
        self.plan = plan_delivery(
            case_key="case-crash-1", source_peer_key="thread:crash-1",
            parts=(Part(1, "text", C, 40), Part(2, "text", D, 35)),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 200, True),
            authority=Authority(9, A, True), choice=Choice(),
        )

    def stage(self):
        return stage_plan(
            self.directory, plan=self.plan, approval=self.approval,
            evidence=self.evidence, verify_approval=self.verify,
            synthetic_fixtures_only=True,
        )

    def reserve(self, intent):
        return reserve_for_adapter(
            self.directory, intent_key=intent.intent_key, plan=self.plan,
            approval=self.approval, evidence=self.evidence,
            verify_approval=self.verify,
            get_current_evidence=lambda case: self.evidence,
            ttl_seconds=5, synthetic_fixtures_only=True,
        )

    def proof(self, reservation):
        return ProviderReceipt(
            reservation.intent_key, "provider-crash-1", "DELIVERED", "receipt-crash-1"
        )

    def record(self, reservation):
        proof = self.proof(reservation)
        return record_provider_receipt(
            self.directory, reservation=reservation, receipt=proof,
            verify_provider_receipt=lambda value: value == proof,
            synthetic_fixtures_only=True,
        )

    def test_staging_claim_and_all_parts_roll_back_if_audit_write_crashes(self):
        from apps.delivery_planner import outbox
        with patch.object(outbox, "_audit", side_effect=RuntimeError("simulated_crash")):
            with self.assertRaisesRegex(RuntimeError, "simulated_crash"):
                self.stage()
        rows = self.stage()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.ordinal for row in rows], [1, 2])
        self.assertEqual([row.state for row in rows], ["STAGED", "STAGED"])
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 2)

    def test_provider_receipt_and_state_roll_back_together_if_audit_write_crashes(self):
        from apps.delivery_planner import outbox
        intent = self.stage()[0]
        reservation = self.reserve(intent)
        with patch.object(outbox, "_audit", side_effect=RuntimeError("simulated_crash")):
            with self.assertRaisesRegex(RuntimeError, "simulated_crash"):
                self.record(reservation)
        current = {row.intent_key: row for row in list_intents(
            self.directory, synthetic_fixtures_only=True
        )}
        self.assertEqual(current[intent.intent_key].state, "RESERVED")
        self.assertEqual(self.record(reservation).state, "DELIVERED")
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertFalse(summary.complete)
        self.assertEqual((summary.delivered_parts, summary.pending_parts), (1, 1))

    def test_late_verified_receipt_racing_expiry_quarantine_never_loses_delivery(self):
        intents = self.stage()
        reservation = self.reserve(intents[0])
        expired_at = datetime.fromisoformat(reservation.until) + timedelta(seconds=1)
        barrier = Barrier(2)

        def quarantine():
            barrier.wait()
            return flag_expired_reservations(
                self.directory, operator_id="operator-crash-1",
                verify_operator=lambda value: value == "operator-crash-1",
                now=expired_at, synthetic_fixtures_only=True,
            )

        def late_receipt():
            barrier.wait()
            return self.record(reservation)

        with ThreadPoolExecutor(max_workers=2) as pool:
            quarantine_future = pool.submit(quarantine)
            receipt_future = pool.submit(late_receipt)
            changed = quarantine_future.result()
            delivered = receipt_future.result()

        self.assertIn(changed, ((), (reservation.intent_key,)))
        self.assertEqual(delivered.state, "DELIVERED")
        current = {row.intent_key: row.state for row in list_intents(
            self.directory, synthetic_fixtures_only=True
        )}
        self.assertEqual(current[reservation.intent_key], "DELIVERED")
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertEqual(summary.state, "PARTIALLY_DELIVERED")
        self.assertFalse(summary.complete)


if __name__ == "__main__":
    unittest.main()
