"""Multiple synthetic requester cases and private tracking token boundaries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch
import os

from django.db import connection, IntegrityError
from django.test import TransactionTestCase
from django.utils import timezone

from apps.delivery_queue import services as queue
from apps.delivery_queue import requester_tracking as tracking
from apps.delivery_queue.models import (
    RequesterTrackingCase, RequesterTrackingToken, RequesterTrackingEvent,
)

A, B, C, D, E = ["%s" % char * 64 for char in "abcde"]


class RequesterTrackingTests(TransactionTestCase):
    """Test-only authorities; no real user or channel identity."""

    def issue(self, case="case-alpha", **overrides):
        params = dict(
            case_key=case, operator_id="synthetic-operator",
            authorize_operator=lambda actor, target: actor == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=2),
        )
        params.update(overrides)
        return tracking.provision_tracking_case(**params)

    def test_two_cases_are_separate_and_secrets_are_never_stored_in_cleartext(self):
        alpha = self.issue("case-alpha")
        beta = self.issue("case-beta")
        self.assertNotEqual(alpha, beta)
        self.assertNotIn(alpha, str(list(RequesterTrackingToken.objects.values())))
        self.assertEqual(RequesterTrackingToken.objects.count(), 2)
        self.assertEqual(tracking.lookup_case_status(alpha)["status"], "RECEIVED")
        self.assertEqual(tracking.lookup_case_status(beta)["status"], "RECEIVED")
        self.assertNotIn("case-beta", str(tracking.lookup_case_status(alpha)))
        self.assertNotIn("case-alpha", str(tracking.lookup_case_status(beta)))

    def test_unknown_invalid_or_forged_tracking_token_is_rejected_without_case_enumeration(self):
        token = self.issue()
        for supplied in ("", "short", " " * 50, "x" * 300, None, True, token[:-1] + "Z"):
            with self.subTest(token_type=type(supplied).__name__), self.assertRaisesRegex(
                tracking.TrackingDenied, "tracking_token_invalid_or_expired",
            ):
                tracking.lookup_case_status(supplied)
        self.assertEqual(tracking.lookup_case_status(token)["status"], "RECEIVED")

    def test_operator_authorization_is_required_and_failures_are_closed(self):
        for authorize in (
            lambda op, target: False,
            lambda op, target: "MUFTI",
            lambda op, target: (_ for _ in ()).throw(RuntimeError("identity unreachable")),
        ):
            with self.assertRaises(tracking.TrackingDenied):
                self.issue(authorize_operator=authorize)
        self.assertEqual(RequesterTrackingCase.objects.count(), 0)

    def test_production_and_disabled_synthetic_writes_cannot_query_database(self):
        from django.test.utils import CaptureQueriesContext
        for override in ({"FATWA_PRODUCTION": "1"}, {"FATWA_WAVE7_SYNTHETIC_WRITES": "0"}):
            with patch.dict(os.environ, override), CaptureQueriesContext(connection) as queries:
                with self.assertRaises(tracking.TrackingDenied):
                    self.issue()
            self.assertEqual(len(queries), 0)

    def test_rotation_revokes_old_token_and_keeps_one_active_grant(self):
        token = self.issue()
        new_token = tracking.rotate_tracking_token(
            case_key="case-alpha", operator_id="synthetic-operator",
            authorize_operator=lambda op, case: op == "synthetic-operator",
            expires_at=timezone.now() + timedelta(days=2),
        )
        with self.assertRaises(tracking.TrackingDenied):
            tracking.lookup_case_status(token)
        self.assertEqual(tracking.lookup_case_status(new_token)["status"], "RECEIVED")
        self.assertEqual(RequesterTrackingToken.objects.filter(revoked_at__isnull=True).count(), 1)
        self.assertEqual(RequesterTrackingToken.objects.count(), 2)

    def test_expiration_is_fail_closed_and_does_not_erase_case_history(self):
        token = self.issue(expires_at=timezone.now() + timedelta(seconds=2))
        later = timezone.now() + timedelta(minutes=2)
        with patch.object(tracking.timezone, "now", return_value=later):
            with self.assertRaises(tracking.TrackingDenied):
                tracking.lookup_case_status(token)
        self.assertEqual(RequesterTrackingCase.objects.count(), 1)

    def test_case_stage_history_is_atomic_and_stale_version_is_rejected(self):
        token = self.issue()
        stage = tracking.advance_tracking_case(
            case_key="case-alpha", expected_revision=1, stage="UNDER_REVIEW",
            actor_id="synthetic-operator",
            authorize_actor=lambda actor, case, stage: True,
        )
        self.assertEqual((stage["status"], stage["revision"]), ("UNDER_REVIEW", 2))
        self.assertEqual(tracking.lookup_case_status(token)["status"], "UNDER_REVIEW")
        with self.assertRaises(tracking.TrackingDenied):
            tracking.advance_tracking_case(
                case_key="case-alpha", expected_revision=1, stage="NEEDS_CLARIFICATION",
                actor_id="synthetic-operator", authorize_actor=lambda *args: True,
            )
        self.assertEqual(RequesterTrackingEvent.objects.count(), 2)

    def test_inadmissible_stage_cannot_forge_fatwa_approval_or_delivery(self):
        self.issue()
        for stage in ("DELIVERED", "MUFTI_APPROVED", "PUBLISHED", "PROVIDER_ACCEPTED"):
            with self.subTest(stage=stage), self.assertRaises(tracking.TrackingDenied):
                tracking.advance_tracking_case(
                    case_key="case-alpha", expected_revision=1, stage=stage,
                    actor_id="synthetic-operator", authorize_actor=lambda *args: True,
                )
        self.assertEqual(RequesterTrackingEvent.objects.count(), 1)

    def test_provider_accepted_is_not_delivered_and_no_other_case_leaks(self):
        alpha, beta = self.issue("case-alpha"), self.issue("case-beta")
        for case, plan, nonce, receipt in (
            ("case-alpha", C, "N" * 40, "approval-alpha"),
            ("case-beta", D, "M" * 40, "approval-beta"),
        ):
            queue.commit_approved_plan(
                receipt_id=receipt, nonce=nonce, approval_fingerprint=A,
                plan_fingerprint=plan, case_key=case, answer_revision=1,
                provider="reply-source", expires_at=timezone.now()+timedelta(minutes=5),
                parts=((1, B),), verify_approval=lambda: True,
            )
        lease = queue.claim_next(
            provider="reply-source", worker_id="worker-synthetic", plan_fingerprint=C,
        )
        queue.record_receipt(
            lease=lease, receipt_reference="provider-alpha-accepted",
            provider_message_id="msg-alpha", reported="ACCEPTED",
            verify_provider_receipt=lambda data: True,
        )
        alpha_status = tracking.lookup_case_status(alpha)
        beta_status = tracking.lookup_case_status(beta)
        self.assertEqual(alpha_status["status"], "DELIVERY_IN_PROGRESS")
        self.assertEqual(beta_status["status"], "PREPARING_DELIVERY")
        self.assertEqual(alpha_status["delivered_parts"], 0)
        self.assertNotIn("case-beta", str(alpha_status))
        self.assertNotIn("case-alpha", str(beta_status))

    def test_legacy_delivered_receipt_is_not_misrepresented_as_verified_delivery(self):
        token = self.issue()
        queue.commit_approved_plan(
            receipt_id="tracking-plan-one", nonce="K" * 40, approval_fingerprint=A,
            plan_fingerprint=C, case_key="case-alpha", answer_revision=1,
            provider="reply-source", expires_at=timezone.now()+timedelta(minutes=5),
            parts=((1, B),), verify_approval=lambda: True,
        )
        lease = queue.claim_next(provider="reply-source", worker_id="worker-synthetic")
        queue.record_receipt(
            lease=lease, receipt_reference="legacy-delivered",
            provider_message_id="msg-legacy", reported="DELIVERED",
            verify_provider_receipt=lambda data: True,
        )
        status = tracking.lookup_case_status(token)
        self.assertEqual(status["status"], "PROVIDER_REPORTED_DELIVERY_UNVERIFIED")
        self.assertFalse(status["delivery_verified"])
        self.assertNotIn("DELIVERED", status["status"])

    def test_immutable_stage_events_cannot_be_edited_or_deleted(self):
        self.issue()
        with self.assertRaises(IntegrityError):
            RequesterTrackingEvent.objects.update(new_stage="PUBLISHED")
        with self.assertRaises(IntegrityError):
            RequesterTrackingEvent.objects.all().delete()
        self.assertEqual(RequesterTrackingEvent.objects.count(), 1)

    def test_reissued_case_does_not_disclose_or_reset_existing_token(self):
        first = self.issue()
        with self.assertRaises(tracking.TrackingDenied):
            self.issue()
        self.assertEqual(RequesterTrackingToken.objects.count(), 1)
        self.assertEqual(tracking.lookup_case_status(first)["status"], "RECEIVED")
