"""No technical review or author draft can masquerade as a MUFTI approval."""
from dataclasses import replace
from datetime import UTC, datetime
import unittest

from apps.delivery_planner.approval import (
    ApprovalReceipt, CurrentEvidence, require_return_approval,
)
from apps.delivery_planner.planner import (
    Authority, Capabilities, Choice, InvalidPlan, Part, plan_delivery,
)

A, B, C = "a" * 64, "b" * 64, "c" * 64


class ApprovalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.receipt = ApprovalReceipt(
            "intake-7", 3, A, B, "", "sheikh-training",
            "MUFTI", "APPROVE_RETURN_TO_ORIGIN", "approval-0123",
            datetime.now(UTC).isoformat(),
        )
        self.current = CurrentEvidence("intake-7", 3, A, B, "")
        self.plan = plan_delivery(
            case_key="intake-7", source_peer_key="thread:Q2",
            parts=(Part(1, "text", C, 14),),
            capabilities=Capabilities("reply-source", "cap-v1", frozenset({"text"}), 100, True),
            authority=Authority(3, A, True), choice=Choice(),
        )

    def check(self, *, receipt=None, evidence=None, verifier=None):
        return require_return_approval(
            receipt=receipt or self.receipt,
            evidence=evidence or self.current,
            plan=self.plan,
            verify_receipt=verifier if verifier is not None else lambda r: r.receipt_id == "approval-0123",
        )

    def test_verified_mufti_receipt_binds_exact_revision_and_evidence(self):
        approved = self.check()
        self.assertEqual(approved.authority.answer_revision, 3)
        self.assertEqual(approved.source_digest, B)
        self.assertEqual(len(approved.approval_fingerprint), 64)
        self.assertEqual(approved.approval_fingerprint, self.check().approval_fingerprint)

    def test_technical_review_and_draft_author_are_not_authorities(self):
        for role in ("ORGANIZER", "ORGANIZER_ADMIN", "TECHNICAL_REVIEWER", "AUTHOR"):
            with self.subTest(role=role), self.assertRaises(InvalidPlan):
                self.check(receipt=replace(self.receipt, approver_role=role))
        with self.assertRaises(InvalidPlan):
            self.check(receipt=replace(self.receipt, decision="TECHNICAL_REVIEW_COMPLETE"))

    def test_any_change_requires_a_new_mufti_decision(self):
        for field, new in (
            ("answer_sha256", C), ("source_digest", C), ("reply_digest", C),
            ("answer_revision", 4), ("source_deleted", True),
            ("clarification_pending", True), ("change_request_open", True),
        ):
            with self.subTest(field=field), self.assertRaises(InvalidPlan):
                self.check(evidence=replace(self.current, **{field: new}))

    def test_forged_missing_or_non_boolean_verifier_fails_closed(self):
        for result in (False, None, 1, "true"):
            with self.subTest(result=result), self.assertRaises(InvalidPlan):
                self.check(verifier=lambda r: result)
        with self.assertRaises(InvalidPlan):
            self.check(verifier=lambda r: 1 / 0)

    def test_case_and_receipt_ids_cannot_be_transferred(self):
        with self.assertRaises(InvalidPlan):
            self.check(receipt=replace(self.receipt, case_key="intake-1"))
        with self.assertRaises(InvalidPlan):
            self.check(receipt=replace(self.receipt, receipt_id="foo/bar"))
        with self.assertRaises(InvalidPlan):
            self.check(receipt=replace(self.receipt, answer_revision=True))


if __name__ == "__main__":
    unittest.main()
