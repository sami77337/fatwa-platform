"""Aggregate delivery status never marks a partial multi-part answer complete."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    ProviderReceipt, record_provider_receipt, reserve_for_adapter, stage_plan,
)
from apps.delivery_planner.outbox_recovery import (
    flag_expired_reservations, plan_delivery_summaries,
)
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery

A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


class MultipartDeliveryLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.evidence = CurrentEvidence("case-multipart-1", 7, A, B, "")
        self.approval = ApprovalReceipt(
            "case-multipart-1", 7, A, B, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "multipart-approval-1",
            datetime.now(UTC).isoformat(),
        )
        self.verify = lambda receipt: receipt == self.approval
        self.plan = plan_delivery(
            case_key="case-multipart-1", source_peer_key="thread:multipart-1",
            parts=(Part(1, "text", C, 40), Part(2, "text", D, 35)),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 200, True),
            authority=Authority(7, A, True), choice=Choice(),
        )

    def stage(self):
        return stage_plan(
            self.directory, plan=self.plan, approval=self.approval,
            evidence=self.evidence, verify_approval=self.verify,
            synthetic_fixtures_only=True,
        )

    def reserve(self, intent):
        return reserve_for_adapter(
            self.directory, intent_key=intent.intent_key,
            plan=self.plan, approval=self.approval, evidence=self.evidence,
            verify_approval=self.verify,
            get_current_evidence=lambda case: self.evidence,
            synthetic_fixtures_only=True,
        )

    def receipt(self, reservation, status, receipt_ref):
        return record_provider_receipt(
            self.directory, reservation=reservation,
            receipt=ProviderReceipt(
                reservation.intent_key, "provider-" + str(reservation.intent_key[:8]),
                status, receipt_ref,
            ),
            verify_provider_receipt=lambda proof: proof.receipt_reference == receipt_ref,
            synthetic_fixtures_only=True,
        )

    def test_no_store_is_empty_and_read_does_not_create_database(self):
        self.assertEqual(plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        ), ())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_one_delivered_part_does_not_complete_two_part_answer(self):
        intents = self.stage()
        self.assertEqual(len(intents), 2)
        first = self.reserve(intents[0])
        second = self.reserve(intents[1])
        self.receipt(first, "DELIVERED", "receipt-part-1")
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertEqual(summary.state, "PARTIALLY_DELIVERED")
        self.assertFalse(summary.complete)
        self.assertEqual((summary.delivered_parts, summary.pending_parts), (1, 1))
        self.receipt(second, "DELIVERED", "receipt-part-2")
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertEqual(summary.state, "DELIVERED")
        self.assertTrue(summary.complete)
        self.assertEqual((summary.delivered_parts, summary.part_count), (2, 2))

    def test_mixed_success_and_failure_is_not_complete(self):
        intents = self.stage()
        first, second = self.reserve(intents[0]), self.reserve(intents[1])
        self.receipt(first, "DELIVERED", "receipt-delivered")
        self.receipt(second, "FAILED", "receipt-failed")
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertEqual(summary.state, "PARTIALLY_FAILED")
        self.assertFalse(summary.complete)
        self.assertEqual((summary.delivered_parts, summary.failed_parts), (1, 1))

    def test_expired_part_marks_whole_plan_needing_reconciliation(self):
        intents = self.stage()
        reservation = self.reserve(intents[0])
        expiry = datetime.fromisoformat(reservation.until) + timedelta(seconds=1)
        flag_expired_reservations(
            self.directory, operator_id="operator-1",
            verify_operator=lambda value: value == "operator-1",
            now=expiry, synthetic_fixtures_only=True,
        )
        summary, = plan_delivery_summaries(
            self.directory, synthetic_fixtures_only=True
        )
        self.assertEqual(summary.state, "NEEDS_RECONCILIATION")
        self.assertFalse(summary.complete)
        self.assertEqual(summary.uncertain_parts, 1)
        self.assertEqual(summary.pending_parts, 1)


if __name__ == "__main__":
    unittest.main()
