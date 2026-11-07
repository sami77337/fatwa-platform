"""Focused delivery planning checks; all data is synthetic."""
import unittest

from apps.delivery_planner.planner import (
    Authority, Capabilities, Choice, InvalidPlan, Part,
    plan_delivery, receipt_state,
)

A = "a" * 64
B = "b" * 64
CAP = Capabilities("youtube-comment", "adapter-v1", frozenset({"text", "link"}), 280, False)
AUTH = Authority(7, A, True)


class PlannerTests(unittest.TestCase):
    def plan(self, parts, *, cap=CAP, choice=Choice(), auth=AUTH):
        return plan_delivery(
            case_key="intake-7", source_peer_key="thread:Q1", parts=parts,
            capabilities=cap, authority=auth, choice=choice,
        )

    def test_plain_text_is_planned_but_never_sent(self):
        plan = self.plan((Part(1, "text", B, 120),))
        self.assertEqual(plan.status, "PLANNED_NOT_SENT")
        self.assertEqual(plan.steps[0].action, "READY_FOR_ADAPTER")
        self.assertEqual(
            receipt_state(planned_step=plan.steps[0], verified_adapter_receipt=True, reported="ACCEPTED"),
            "SENT_UNCONFIRMED",
        )
        self.assertEqual(
            receipt_state(planned_step=plan.steps[0], verified_adapter_receipt=True, reported="DELIVERED"),
            "DELIVERED",
        )
        with self.assertRaises(InvalidPlan):
            receipt_state(planned_step=plan.steps[0], verified_adapter_receipt=False, reported="DELIVERED")

    def test_audio_needs_explicit_link_or_human_action(self):
        audio = Part(1, "audio", B, 19000)
        blocked = self.plan((audio,))
        self.assertEqual((blocked.status, blocked.steps[0].action),
                         ("REQUIRES_HUMAN_DECISION", "HUMAN_ACTION_REQUIRED"))
        with self.assertRaises(InvalidPlan):
            self.plan((audio,), choice=Choice(use_public_link=True, published_url="https://site.invalid/f/1"))
        approved = self.plan((audio,), choice=Choice(True, True, "https://site.invalid/f/1"))
        self.assertEqual(approved.steps[0].action, "PUBLISHED_LINK_OPTION")
        self.assertNotEqual(
            approved.steps[0].idempotency_key,
            self.plan((audio,), choice=Choice(True, True, "https://site.invalid/f/2")).steps[0].idempotency_key,
        )
        with self.assertRaises(InvalidPlan):
            self.plan((audio,), choice=Choice(True, True, "https://site.invalid:bad/f"))
        with self.assertRaises(InvalidPlan):
            receipt_state(planned_step=approved.steps[0], verified_adapter_receipt=True, reported="DELIVERED")

    def test_text_over_limit_is_not_silently_truncated(self):
        self.assertEqual(
            self.plan((Part(1, "text", B, 281),)).steps[0].reason,
            "text_segmentation_required",
        )

    def test_reject_unverified_authority_or_invalid_parts(self):
        with self.assertRaises(InvalidPlan):
            self.plan((Part(1, "text", B, 1),), auth=Authority(7, A, False))
        with self.assertRaises(InvalidPlan):
            self.plan((Part(2, "text", B, 1),))
        with self.assertRaises(InvalidPlan):
            self.plan((Part(True, "text", B, 1),))

    def test_idempotency_key_tracks_approved_revision(self):
        parts = (Part(1, "text", B, 5),)
        key = self.plan(parts).steps[0].idempotency_key
        self.assertEqual(key, self.plan(parts).steps[0].idempotency_key)
        self.assertNotEqual(key, self.plan(parts, auth=Authority(8, A, True)).steps[0].idempotency_key)
