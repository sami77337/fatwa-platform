"""Atomic local approval-to-plan claims prevent receipt reuse across plans."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from dataclasses import replace

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import FILE_NAME, OutboxConflict, list_intents, stage_plan
from apps.delivery_planner.planner import Authority, Capabilities, Choice, InvalidPlan, Part, plan_delivery

A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


class AtomicApprovalCommitTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.evidence = CurrentEvidence("case-atomic-1", 4, A, B, "")
        self.approval = ApprovalReceipt(
            "case-atomic-1", 4, A, B, "", "mufti-training", "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN", "receipt-atomic-1",
            datetime.now(UTC).isoformat(),
        )
        self.verify = lambda receipt: receipt == self.approval

    def plan(self, *, digest=C, source="thread:atomic-1"):
        return plan_delivery(
            case_key="case-atomic-1", source_peer_key=source,
            parts=(Part(1, "text", digest, 17),),
            capabilities=Capabilities("reply-source", "v1", frozenset({"text"}), 200, True),
            authority=Authority(4, A, True), choice=Choice(),
        )

    def stage(self, plan):
        return stage_plan(
            self.directory, plan=plan, approval=self.approval,
            evidence=self.evidence, verify_approval=self.verify,
            synthetic_fixtures_only=True,
        )

    def claims(self):
        with sqlite3.connect(self.directory / FILE_NAME) as con:
            return con.execute("SELECT * FROM approval_claims").fetchall()

    def test_same_approval_and_exact_plan_are_idempotent_across_restart(self):
        plan = self.plan()
        first = self.stage(plan)
        second = self.stage(plan)
        self.assertEqual(first, second)
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 1)

    def test_one_receipt_cannot_authorize_a_different_plan_or_source(self):
        self.stage(self.plan())
        for changed in (self.plan(digest=D), self.plan(source="thread:other")):
            with self.subTest(plan=changed), self.assertRaisesRegex(
                OutboxConflict, "approval_receipt_replay_or_changed_plan"
            ):
                self.stage(changed)
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 1)

    def test_parallel_duplicate_stage_commits_one_claim_and_one_intent(self):
        plan = self.plan()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.stage(plan), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 1)

    def test_parallel_competing_plans_allow_exactly_one_claim(self):
        plans = (self.plan(digest=C), self.plan(digest=D))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.stage, plan) for plan in plans]
            results = []
            for future in futures:
                try:
                    results.append(("PASS", future.result()))
                except OutboxConflict as exc:
                    results.append(("DENY", str(exc)))
        self.assertEqual(sorted(item[0] for item in results), ["DENY", "PASS"])
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(len(list_intents(self.directory, synthetic_fixtures_only=True)), 1)

    def test_claims_are_append_only_and_schema_tampering_fails_closed(self):
        self.stage(self.plan())
        with sqlite3.connect(self.directory / FILE_NAME) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM approval_claims")
            con.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE approval_claims SET plan_fingerprint=?", (D,))
            con.rollback()
            con.execute("DROP TRIGGER immutable_approval_claims_update")
            con.commit()
        with self.assertRaisesRegex(OutboxConflict, "outbox_schema_mismatch"):
            list_intents(self.directory, synthetic_fixtures_only=True)

    def test_invalid_receipt_identity_is_rejected_before_creating_the_outbox(self):
        broken = replace(self.approval, receipt_id="../transfer")
        with self.assertRaisesRegex(InvalidPlan, "invalid_or_non_mufti_approval"):
            stage_plan(
                self.directory, plan=self.plan(), approval=broken,
                evidence=self.evidence, verify_approval=lambda _: True,
                synthetic_fixtures_only=True,
            )
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
