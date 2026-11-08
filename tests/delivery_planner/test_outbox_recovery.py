"""An uncertain send never becomes eligible for automated retry."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    OutboxConflict, ProviderReceipt, list_intents, record_provider_receipt,
    reserve_for_adapter, stage_plan,
)
from apps.delivery_planner.outbox_recovery import (
    flag_expired_reservations, reconciliation_queue,
)
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery

A, B = "a" * 64, "b" * 64


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.plan = plan_delivery(
            case_key="intake-7", source_peer_key="thread:T1",
            parts=(Part(1, "text", B, 15),),
            capabilities=Capabilities("comment", "v1", frozenset({"text"}), 280, False),
            authority=Authority(2, A, True), choice=Choice(),
        )
        self.receipt = ApprovalReceipt(
            "intake-7", 2, A, B, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "decision-1", datetime.now(UTC).isoformat(),
        )
        self.evidence = CurrentEvidence("intake-7", 2, A, B, "")
        self.verify = lambda receipt: receipt.receipt_id == "decision-1"

    def reserve(self):
        (intent,) = stage_plan(
            self.directory, plan=self.plan, approval=self.receipt,
            evidence=self.evidence, verify_approval=self.verify,
            synthetic_fixtures_only=True,
        )
        reservation = reserve_for_adapter(
            self.directory, intent_key=intent.intent_key,
            plan=self.plan, approval=self.receipt, evidence=self.evidence,
            verify_approval=self.verify, ttl_seconds=5,
            get_current_evidence=lambda key: self.evidence if key == "intake-7" else None,
            synthetic_fixtures_only=True,
        )
        return intent, reservation

    def flag(self, now, *, identity="operator-1", verifier=None):
        return flag_expired_reservations(
            self.directory, operator_id=identity,
            verify_operator=verifier or (lambda value: value == "operator-1"),
            now=now, synthetic_fixtures_only=True,
        )

    def test_absent_store_does_not_create_file(self):
        self.assertEqual(reconciliation_queue(self.directory, synthetic_fixtures_only=True), ())
        self.assertEqual(self.flag(datetime.now(UTC)), ())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_expired_reservation_quarantined_not_reissued(self):
        intent, reservation = self.reserve()
        now = datetime.fromisoformat(reservation.until) + timedelta(microseconds=1)
        before = reconciliation_queue(self.directory, now=now, synthetic_fixtures_only=True)
        self.assertEqual(before[0].attention, "UNCERTAIN_RESERVATION_EXPIRED")
        self.assertEqual(self.flag(now), (intent.intent_key,))
        self.assertEqual(self.flag(now), ())
        reopened = reconciliation_queue(self.directory, synthetic_fixtures_only=True)
        self.assertEqual(reopened[0].saved_state, "UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertEqual(reopened[0].attention, "NEEDS_MANUAL_RECONCILIATION_NO_RETRY")
        with self.assertRaises(OutboxConflict):
            reserve_for_adapter(
                self.directory, intent_key=intent.intent_key, plan=self.plan,
                approval=self.receipt, evidence=self.evidence, verify_approval=self.verify,
                get_current_evidence=lambda key: self.evidence,
                synthetic_fixtures_only=True,
            )
        (same,) = stage_plan(
            self.directory, plan=self.plan, approval=self.receipt, evidence=self.evidence,
            verify_approval=self.verify, synthetic_fixtures_only=True,
        )
        self.assertEqual(same.state, "UNKNOWN_REQUIRES_RECONCILIATION")

    def test_verified_late_receipt_closes_unknown_but_unverified_is_refused(self):
        intent, reservation = self.reserve()
        self.flag(datetime.fromisoformat(reservation.until) + timedelta(seconds=1))
        receipt = ProviderReceipt(intent.intent_key, "provider-msg-1", "DELIVERED", "callback-1")
        with self.assertRaises(OutboxConflict):
            record_provider_receipt(
                self.directory, reservation=reservation, receipt=receipt,
                verify_provider_receipt=lambda r: False, synthetic_fixtures_only=True,
            )
        result = record_provider_receipt(
            self.directory, reservation=reservation, receipt=receipt,
            verify_provider_receipt=lambda r: r.receipt_reference == "callback-1",
            synthetic_fixtures_only=True,
        )
        self.assertEqual(result.state, "DELIVERED")
        self.assertEqual(reconciliation_queue(self.directory, synthetic_fixtures_only=True), ())

    def test_denied_operator_or_early_clock_cannot_quarantine(self):
        intent, reservation = self.reserve()
        early = datetime.fromisoformat(reservation.until) - timedelta(seconds=1)
        self.assertEqual(self.flag(early), ())
        with self.assertRaises(OutboxConflict):
            self.flag(datetime.now(UTC) + timedelta(hours=2), verifier=lambda r: False)
        with self.assertRaises(OutboxConflict):
            self.flag(datetime.now(UTC) + timedelta(hours=2), identity="../other")
        self.assertEqual(
            list_intents(self.directory, synthetic_fixtures_only=True)[0].state, "RESERVED"
        )


if __name__ == "__main__":
    unittest.main()
