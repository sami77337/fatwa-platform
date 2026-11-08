"""Local persistent outbox tests: no adapter network activity or real approvals."""
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    OutboxConflict, ProviderReceipt, list_intents, record_provider_receipt,
    reserve_for_adapter, stage_plan,
)
from apps.delivery_planner.planner import (
    Authority, Capabilities, Choice, InvalidPlan, Part, plan_delivery,
)

A, B, C = "a" * 64, "b" * 64, "c" * 64


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.plan = plan_delivery(
            case_key="intake-7", source_peer_key="thread:Q1",
            parts=(Part(1, "text", C, 12), Part(2, "audio", B, 1000)),
            capabilities=Capabilities("youtube-comment", "v1", frozenset({"text", "link"}), 280, False),
            authority=Authority(3, A, True), choice=Choice(),
        )
        self.receipt = ApprovalReceipt(
            "intake-7", 3, A, B, "", "sheikh-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "approval-3", datetime.now(UTC).isoformat(),
        )
        self.evidence = CurrentEvidence("intake-7", 3, A, B, "")
        self.verifier = lambda r: r.receipt_id == "approval-3"

    def stage(self):
        return stage_plan(
            self.dir, plan=self.plan, approval=self.receipt,
            evidence=self.evidence, verify_approval=self.verifier,
            synthetic_fixtures_only=True,
        )

    def reserve(self, key):
        return reserve_for_adapter(
            self.dir, intent_key=key, plan=self.plan, approval=self.receipt,
            evidence=self.evidence, verify_approval=self.verifier,
            get_current_evidence=lambda key: self.evidence if key == "intake-7" else None,
            synthetic_fixtures_only=True,
        )

    def reconcile(self, reservation, status, message="provider-01"):
        return record_provider_receipt(
            self.dir, reservation=reservation,
            receipt=ProviderReceipt(reservation.intent_key, message, status, "receipt-01"),
            verify_provider_receipt=lambda proof: proof.receipt_reference == "receipt-01",
            synthetic_fixtures_only=True,
        )

    def test_stage_preserves_multiple_parts_across_restart_and_holds_audio(self):
        rows = self.stage()
        self.assertEqual([r.state for r in rows], ["STAGED", "HELD_FOR_HUMAN"])
        self.assertEqual(len(list_intents(self.dir, synthetic_fixtures_only=True)), 2)
        self.assertEqual(rows, self.stage())
        with self.assertRaises(OutboxConflict):
            self.reserve(rows[1].intent_key)
        self.assertEqual(len(list_intents(self.dir, synthetic_fixtures_only=True)), 2)

    def test_mufti_approval_is_verified_before_creating_the_file(self):
        with self.assertRaises(InvalidPlan):
            stage_plan(
                self.dir, plan=self.plan,
                approval=replace(self.receipt, approver_role="ORGANIZER"),
                evidence=self.evidence, verify_approval=self.verifier,
                synthetic_fixtures_only=True,
            )
        self.assertEqual(list(self.dir.iterdir()), [])
        with self.assertRaises(InvalidPlan):
            stage_plan(
                self.dir, plan=self.plan, approval=self.receipt,
                evidence=replace(self.evidence, source_digest=C),
                verify_approval=self.verifier, synthetic_fixtures_only=True,
            )
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_reservation_and_receipt_do_not_confuse_accepted_with_delivered(self):
        key = self.stage()[0].intent_key
        claim = self.reserve(key)
        with self.assertRaises(OutboxConflict):
            self.reserve(key)
        accepted = self.reconcile(claim, "ACCEPTED")
        self.assertEqual(accepted.state, "SENT_UNCONFIRMED")
        self.assertEqual(self.reconcile(claim, "ACCEPTED").state, "SENT_UNCONFIRMED")
        self.assertEqual(self.reconcile(claim, "DELIVERED").state, "DELIVERED")
        with self.assertRaises(OutboxConflict):
            self.reconcile(claim, "ACCEPTED")
        latest = {r.intent_key: r.state for r in list_intents(self.dir, synthetic_fixtures_only=True)}
        self.assertEqual(latest[key], "DELIVERED")

    def test_unsafe_receipt_and_changed_source_are_denied(self):
        key = self.stage()[0].intent_key
        with self.assertRaises(InvalidPlan):
            reserve_for_adapter(
                self.dir, intent_key=key, plan=self.plan, approval=self.receipt,
                evidence=replace(self.evidence, clarification_pending=True),
                verify_approval=self.verifier,
                get_current_evidence=lambda key: self.evidence,
                synthetic_fixtures_only=True,
            )
        claim = self.reserve(key)
        with self.assertRaises(OutboxConflict):
            record_provider_receipt(
                self.dir, reservation=claim,
                receipt=ProviderReceipt(key, "provider-01", "DELIVERED", "receipt-01"),
                verify_provider_receipt=lambda proof: False,
                synthetic_fixtures_only=True,
            )
        self.assertEqual(self.reconcile(claim, "ACCEPTED", "provider-01").state, "SENT_UNCONFIRMED")
        with self.assertRaises(OutboxConflict):
            self.reconcile(claim, "DELIVERED", "provider-02")

    def test_reservation_refuses_missing_reader_and_stale_canonical_evidence(self):
        key = self.stage()[0].intent_key
        options = dict(
            directory=self.dir, intent_key=key, plan=self.plan,
            approval=self.receipt, evidence=self.evidence,
            verify_approval=self.verifier, synthetic_fixtures_only=True,
        )
        with self.assertRaisesRegex(OutboxConflict, "current_evidence_reader_required"):
            reserve_for_adapter(**options)
        with self.assertRaisesRegex(OutboxConflict, "current_evidence_changed"):
            reserve_for_adapter(
                **options,
                get_current_evidence=lambda case: replace(self.evidence, source_digest=C),
            )
        with self.assertRaisesRegex(OutboxConflict, "current_evidence_reader_unavailable"):
            reserve_for_adapter(
                **options,
                get_current_evidence=lambda case: 1 / 0,
            )
        self.assertEqual(
            {row.intent_key: row.state for row in list_intents(
                self.dir, synthetic_fixtures_only=True,
            )}[key],
            "STAGED",
        )
        reserved = reserve_for_adapter(
            **options,
            get_current_evidence=lambda case: self.evidence,
        )
        self.assertEqual(reserved.intent_key, key)

    def test_production_is_never_activated(self):
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
            with self.assertRaises(ValueError):
                self.stage()
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
