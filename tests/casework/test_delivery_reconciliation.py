"""Current-case delivery follow-up; no real provider, sender or requester data."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.db import connections, transaction
from django.test import TransactionTestCase

from apps.casework import delivery_reconciliation as r
from apps.casework import services as s
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryAttempt,
    DeliveryAuditEvent,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
)
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory


class DeliveryReconciliationTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.approved = self.approve()
        self.plan = self.stage()["plan_sha256"]

    def report(self, case=None, **changes):
        return r.read_case_delivery_followup(
            **{
                **self.staff(case),
                "verifier": self.channel_verifier,
                **changes,
            }
        )

    def quarantine(self, case=None, **changes):
        return r.quarantine_case_delivery(
            **{
                **self.staff(case),
                "expected_plan_sha256": self.plan,
                "verifier": self.channel_verifier,
                **changes,
            }
        )

    def snapshot(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (
                ApprovalClaim,
                DeliveryIntent,
                DeliveryAttempt,
                ProviderReceipt,
                ProviderSignatureEvidence,
                DeliveryAuditEvent,
            )
        ]

    def test_report_tracks_staged_accepted_partial_and_verified_without_writes(self):
        report = self.report()
        self.assertEqual(report["queue_state"], "STAGED")
        self.assertTrue(
            all(p["next_action"] == "TRUSTED_RESERVATION_REQUIRED" for p in report["parts"])
        )
        lease = self.reserve()
        self.record(lease, self.event(lease, reported="ACCEPTED"))
        report = self.report()
        self.assertEqual(report["parts"][0]["next_action"], "AWAIT_PROVIDER_OUTCOME")
        self.assertFalse(report["delivery_verified"])
        self.record(lease)
        self.assertEqual(self.report()["parts"][0]["provider_evidence"], "VERIFIED_PROVIDER_REPORT")
        self.assertFalse(self.report()["delivery_verified"])
        self.deliver()
        before = self.snapshot()
        report = self.report()
        self.assertTrue(report["delivery_verified"])
        self.assertFalse(report["read_confirmed"])
        self.assertFalse(report["automatic_retry_allowed"])
        self.assertTrue(all(p["next_action"] == "NO_ACTION" for p in report["parts"]))
        self.assertEqual(before, self.snapshot())

    def test_expired_lease_read_is_nonmutating_and_calls_for_quarantine(self):
        lease = self.reserve()
        before = self.snapshot()
        with patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)):
            report = self.report()
        self.assertEqual(report["quarantinable_parts"], 1)
        self.assertEqual(report["parts"][0]["next_action"], "QUARANTINE_EXPIRED_ATTEMPT")
        self.assertEqual(report["parts"][0]["state"], "LEASED")
        self.assertEqual(before, self.snapshot())

    def test_quarantine_only_current_case_expired_parts_without_new_attempts(self):
        b = self.intake("b")
        self.directory.refs |= frozenset([b["public_ref"]])
        self.approve(b)
        self.stage(b)
        first, foreign = self.reserve(), self.reserve(b)
        attempts = list(DeliveryAttempt.objects.order_by("pk").values())
        with patch.object(
            r.timezone,
            "now",
            return_value=max(first.expires_at, foreign.expires_at) + timedelta(seconds=1),
        ):
            report = self.quarantine()
        self.assertEqual(report["quarantined_parts"], 1)
        self.assertEqual(report["parts"][0]["state"], "UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertEqual(report["parts"][0]["next_action"], "REVIEW_PROVIDER_OUTCOME_NO_RETRY")
        self.assertEqual(DeliveryIntent.objects.get(pk=foreign.intent_key).state, "LEASED")
        self.assertEqual(attempts, list(DeliveryAttempt.objects.order_by("pk").values()))
        # Staged parts are not quarantined or silently reserved.
        self.assertEqual(
            DeliveryIntent.objects.filter(plan_fingerprint=self.plan, state="STAGED").count(),
            report["expected_parts"] - 1,
        )

    def test_repeated_quarantine_is_idempotent_and_never_reissues_same_part(self):
        lease = self.reserve()
        with patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.quarantine()["quarantined_parts"], 1)
            before = self.snapshot()
            self.assertEqual(self.quarantine()["quarantined_parts"], 0)
            self.assertEqual(before, self.snapshot())
        next_lease = self.reserve()
        self.assertNotEqual(lease.intent_key, next_lease.intent_key)
        self.assertEqual(DeliveryAttempt.objects.filter(intent_id=lease.intent_key).count(), 1)

    def test_late_signed_provider_result_resolves_original_quarantined_attempt(self):
        lease = self.reserve()
        event = self.event(lease)
        with patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)):
            self.quarantine()
        self.record(lease, event)
        self.deliver()
        result = self.report()
        self.assertTrue(result["delivery_verified"])
        self.assertFalse(result["read_confirmed"])
        self.assertEqual(result["parts"][0]["state"], "DELIVERED")

    def test_live_lease_and_accepted_report_are_not_quarantined(self):
        first = self.reserve()
        self.assertEqual(self.quarantine()["quarantined_parts"], 0)
        self.record(first, self.event(first, reported="ACCEPTED"))
        with patch.object(r.timezone, "now", return_value=first.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.quarantine()["quarantined_parts"], 0)
        self.assertEqual(DeliveryIntent.objects.get(pk=first.intent_key).state, "SENT_UNCONFIRMED")

    def test_wrong_or_stale_plan_cannot_mutate_current_or_other_case(self):
        lease = self.reserve()
        before = self.snapshot()
        for plan in ("a" * 64, "", None, True, "g" * 64):
            with self.subTest(plan=plan), self.assertRaises(s.CaseConflict):
                self.quarantine(expected_plan_sha256=plan)
        self.assertEqual(before, self.snapshot())
        s.add_followup(
            token=self.a["token"],
            text="واقعة جديدة",
            expected_revision=self.approved["revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(s.CaseConflict):
            self.quarantine()
        self.approve()
        self.stage()
        with self.assertRaisesRegex(s.CaseConflict, "case_delivery_plan_changed"):
            self.quarantine()
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")

    def test_foreign_case_organizer_and_changed_identity_are_denied(self):
        self.reserve()
        before = self.snapshot()
        for directory in (
            TestDirectory(["foreign"]),
            TestDirectory([self.a["public_ref"]], role="ORGANIZER_ADMIN"),
            TestDirectory([self.a["public_ref"]], epoch="new-epoch"),
        ):
            with self.assertRaises(s.CaseConflict):
                self.report(provider=directory)
            with self.assertRaises(s.CaseConflict):
                self.quarantine(provider=directory)
        self.assertEqual(before, self.snapshot())

    def test_audit_failure_rolls_back_all_quarantine_changes(self):
        lease = self.reserve()
        before = self.snapshot()
        with (
            patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)),
            patch.object(
                queue,
                "_audit",
                side_effect=RuntimeError("synthetic-fault"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.quarantine()
        self.assertEqual(before, self.snapshot())

    def test_epoch_change_during_projection_rolls_back_quarantine(self):
        lease = self.reserve()
        before = self.snapshot()
        original = r._report

        def changed(*args):
            result = original(*args)
            self.directory.epoch = "revoked-during-report"
            return result

        with (
            patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)),
            patch.object(
                r,
                "_report",
                side_effect=changed,
            ),
        ):
            with self.assertRaises(s.CaseConflict):
                self.quarantine()
        self.assertEqual(before, self.snapshot())

    def test_quarantine_and_late_receipt_race_preserves_provider_delivery(self):
        lease = self.reserve()
        event = self.event(lease)

        def run(operation):
            connections.close_all()
            try:
                return operation()
            finally:
                connections.close_all()

        with (
            patch.object(r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [
                pool.submit(run, self.quarantine),
                pool.submit(run, lambda: self.record(lease, event)),
            ]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state, "DELIVERED")
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        queue.verify_audit_chain()

    def test_unsigned_missing_and_revoked_proofs_have_actionable_non_delivery_status(self):
        first = self.reserve()
        queue.record_receipt(
            lease=first,
            receipt_reference="legacy-" + secrets.token_hex(8),
            provider_message_id="legacy-message",
            reported="DELIVERED",
            verify_provider_receipt=lambda _: True,
        )
        self.deliver()
        report = self.report()
        self.assertFalse(report["delivery_verified"])
        self.assertEqual(report["parts"][0]["provider_evidence"], "UNVERIFIED")
        self.assertEqual(report["parts"][0]["next_action"], "CHECK_SIGNED_EVIDENCE")
        unavailable = self.report(verifier=None)
        self.assertFalse(unavailable["delivery_verified"])
        self.assertEqual(unavailable["delivery_status"], "EVIDENCE_UNAVAILABLE")
        revoked = self.report(verifier=self.verifier(revoked_key_ids=frozenset({"channel-key"})))
        self.assertFalse(revoked["delivery_verified"])
        self.assertTrue(
            all(p["provider_evidence"] != "VERIFIED_PROVIDER_REPORT" for p in revoked["parts"])
        )

    def test_failed_provider_result_requires_human_review_and_cannot_be_retried(self):
        first = self.reserve()
        self.record(first, self.event(first, reported="FAILED"))
        report = self.report()
        self.assertEqual(report["parts"][0]["next_action"], "REVIEW_PROVIDER_OUTCOME_NO_RETRY")
        with patch.object(r.timezone, "now", return_value=first.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.quarantine()["quarantined_parts"], 0)
        self.assertNotEqual(self.reserve().intent_key, first.intent_key)

    def test_report_has_no_text_tracking_token_worker_secret_or_other_case(self):
        b = self.intake("b")
        lease = self.reserve()
        event = self.event(lease)
        self.record(lease, event)
        text = str(self.report())
        for private in (
            self.a["token"],
            self.a["case_id"],
            b["public_ref"],
            lease.token,
            lease.intent_key,
            lease.owner,
            event.signature_b64url,
            event.receipt_reference,
            event.provider_message_id,
            self.approved["answers"][-1]["text"],
            "requester-a",
        ):
            self.assertNotIn(private, text)

    def test_expired_authorization_does_not_offer_reservation_or_renew_it(self):
        expires = ApprovalClaim.objects.get(plan_fingerprint=self.plan).expires_at
        with patch.object(r.timezone, "now", return_value=expires + timedelta(seconds=1)):
            report = self.report()
            self.assertTrue(report["authorization_expired"])
            self.assertTrue(
                all(p["next_action"] == "NEW_MUFTI_REVIEW_REQUIRED" for p in report["parts"])
            )
            self.assertEqual(self.quarantine()["quarantined_parts"], 0)
        self.assertEqual(ApprovalClaim.objects.get(plan_fingerprint=self.plan).expires_at, expires)

    def test_missing_ack_and_invalid_queue_plan_filter_are_denied(self):
        for operation in (self.report, self.quarantine):
            with self.assertRaises(s.CaseConflict):
                operation(synthetic_fixtures_only=False)
        with self.assertRaises(queue.QueueConflict):
            queue.quarantine_expired_leases(plan_fingerprint="invalid")

    def test_revocation_between_summary_and_part_checks_cannot_report_verified(self):
        self.deliver()
        count = 0
        parts = ApprovalClaim.objects.get(plan_fingerprint=self.plan).expected_parts

        def revoked(_):
            nonlocal count
            count += 1
            return count > parts

        report = self.report(verifier=self.verifier(is_key_revoked=revoked))
        self.assertFalse(report["delivery_verified"])
        self.assertEqual(report["delivery_status"], "PROVIDER_EVIDENCE_INCOMPLETE")
        self.assertTrue(all(p["provider_evidence"] == "UNVERIFIED" for p in report["parts"]))

    def test_busy_part_is_skipped_without_claiming_reconciliation_is_complete(self):
        lease = self.reserve()
        locked, release = Event(), Event()

        def holder():
            connections.close_all()
            try:
                with transaction.atomic():
                    DeliveryIntent.objects.select_for_update().get(pk=lease.intent_key)
                    locked.set()
                    if not release.wait(10):
                        raise RuntimeError("synthetic-lock-timeout")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            held = pool.submit(holder)
            try:
                self.assertTrue(locked.wait(10))
                with patch.object(
                    r.timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)
                ):
                    report = self.quarantine()
                self.assertEqual(report["quarantined_parts"], 0)
                self.assertEqual(report["quarantinable_parts"], 1)
                self.assertEqual(report["parts"][0]["state"], "LEASED")
            finally:
                release.set()
            held.result(timeout=10)
