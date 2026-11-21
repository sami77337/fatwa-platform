"""A preserved failure closes only through its exact fully verified retry ancestry."""

import secrets
from datetime import timedelta

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.composite_delivery.test_retry import FEATURES, RetryFixture
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent

from . import test_delivery
from .models import LifecycleEvent
from .tests import Authority


@override_settings(**{**FEATURES, "FATWA_CASE_LIFECYCLE_ENABLED": True})
class RetryClosureTests(RetryFixture, TransactionTestCase):
    close = test_delivery.DeliveryClosureTests.close

    def setUp(self):
        super().setUp()
        configured = override_settings(
            FATWA_CASE_LIFECYCLE_AUTHORITY=Authority(
                [self.a["public_ref"]], self.directory.provider_id
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def repaired(self):
        parent, _ = self.failed()
        self.retry_stage(self.retry_request(parent))
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "DELIVERED")
        return parent

    def test_only_all_current_successful_leaves_close_and_original_failed_plan_is_retained(self):
        parent, _ = self.failed()
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        self.retry_stage(self.retry_request(parent))
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        lease = self.reserve()
        part = self.resolve(lease)
        self.outcome(lease, part, "ACCEPTED")
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        self.outcome(lease, part, "DELIVERED")
        before = list(DeliveryIntent.objects.order_by("pk").values())
        self.assertEqual(self.close()["state"], "CLOSED")
        proof = LifecycleEvent.objects.get().context
        self.assertEqual(proof["delivery"], "SIGNED_COMPLETE")
        self.assertEqual(proof["plans"][0]["original_state"], "PARTIALLY_FAILED")
        self.assertEqual(len(proof["plans"][0]["retry_plans"]), 2)
        self.assertEqual(before, list(DeliveryIntent.objects.order_by("pk").values()))

    def test_unrelated_unbound_claim_still_blocks_after_successful_retry(self):
        self.repaired()
        fingerprint = secrets.token_hex(32)
        queue.commit_approved_plan(
            receipt_id="unrelated-approval",
            nonce=secrets.token_urlsafe(32),
            approval_fingerprint=secrets.token_hex(32),
            plan_fingerprint=fingerprint,
            case_key=self.a["public_ref"],
            answer_revision=self.request()["evidence"]["answer_revision"],
            provider="composite-simulator",
            expires_at=timezone.now() + timedelta(minutes=5),
            parts=((1, secrets.token_hex(32)),),
            verify_approval=lambda: True,
        )
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_binding_invalid"):
            self.close()
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_new_answer_success_never_reconciles_an_unretried_old_failed_plan(self):
        self.failed()
        self.approve()
        self.stage()
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        self.assertTrue(self.status()["delivery_verified"])
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_revoked_failure_verifier_or_disabled_retry_cannot_close_reconciled_chain(self):
        self.repaired()
        with (
            override_settings(FATWA_COMPOSITE_RETRY_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.close()
        self.channel_verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        self.assertEqual(LifecycleEvent.objects.count(), 0)
