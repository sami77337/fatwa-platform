"""Outbox must reject impossible saved receipt and reservation states."""
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.planner import Authority, Capabilities, Choice, Part, plan_delivery
from apps.delivery_planner.outbox import (
    FILE_NAME, OutboxConflict, ProviderReceipt, list_intents,
    record_provider_receipt, reserve_for_adapter, stage_plan,
)


class OutboxIntegrityTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        a, b = "a" * 64, "b" * 64
        self.plan = plan_delivery(
            case_key="intake-7", source_peer_key="thread:T1",
            parts=(Part(1, "text", b, 9),),
            capabilities=Capabilities("channel", "v1", frozenset({"text"}), 200, False),
            authority=Authority(2, a, True), choice=Choice(),
        )
        self.approval = ApprovalReceipt(
            "intake-7", 2, a, b, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "decision-1", datetime.now(UTC).isoformat(),
        )
        self.evidence = CurrentEvidence("intake-7", 2, a, b, "")
        self.verify = lambda r: r.receipt_id == "decision-1"

    def stage(self):
        return stage_plan(
            self.directory, plan=self.plan, approval=self.approval,
            evidence=self.evidence, verify_approval=self.verify,
            synthetic_fixtures_only=True,
        )[0]

    def reserve(self):
        intent = self.stage()
        reservation = reserve_for_adapter(
            self.directory, intent_key=intent.intent_key, plan=self.plan,
            approval=self.approval, evidence=self.evidence,
            verify_approval=self.verify,
            get_current_evidence=lambda key: self.evidence,
            synthetic_fixtures_only=True,
        )
        return reservation

    def mutate(self, assignments):
        con = sqlite3.connect(self.directory / FILE_NAME)
        try:
            con.execute("UPDATE intents SET " + assignments)
            con.commit()
        finally:
            con.close()

    def test_valid_stage_and_reservation_survive_reopen(self):
        claim = self.reserve()
        (intent,) = list_intents(self.directory, synthetic_fixtures_only=True)
        self.assertEqual((intent.state, intent.intent_key), ("RESERVED", claim.intent_key))

    def test_missing_reservation_details_are_rejected(self):
        self.reserve()
        self.mutate("reservation_sha=NULL,reservation_until=NULL")
        with self.assertRaises(OutboxConflict):
            list_intents(self.directory, synthetic_fixtures_only=True)

    def test_provider_status_must_match_saved_state(self):
        claim = self.reserve()
        record_provider_receipt(
            self.directory, reservation=claim,
            receipt=ProviderReceipt(claim.intent_key, "provider-01", "ACCEPTED", "receipt-01"),
            verify_provider_receipt=lambda r: True,
            synthetic_fixtures_only=True,
        )
        self.mutate("provider_status='DELIVERED'")
        with self.assertRaises(OutboxConflict):
            list_intents(self.directory, synthetic_fixtures_only=True)

    def test_received_message_identity_cannot_disappear(self):
        claim = self.reserve()
        record_provider_receipt(
            self.directory, reservation=claim,
            receipt=ProviderReceipt(claim.intent_key, "provider-01", "DELIVERED", "receipt-01"),
            verify_provider_receipt=lambda r: True,
            synthetic_fixtures_only=True,
        )
        self.mutate("provider_message_id=NULL")
        with self.assertRaises(OutboxConflict):
            list_intents(self.directory, synthetic_fixtures_only=True)

    def test_corrupt_timestamp_is_rejected(self):
        self.stage()
        self.mutate("updated_at='not-a-time'")
        with self.assertRaises(OutboxConflict):
            list_intents(self.directory, synthetic_fixtures_only=True)
