"""Synthetic end-to-end case/approval/provider evidence, using actual PostgreSQL."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.casework import delivery as d
from apps.casework import services as s
from apps.casework.models import CaseDecision, CaseDelivery
from apps.delivery_planner.planner import InvalidPlan
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryAuditEvent,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
    SignedDeliveryContext,
)
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory


class CaseDeliveryTests(CaseDeliveryFixture, TransactionTestCase):
    def test_composed_fixture_intakes_stay_separate_and_preserve_each_seed_replay(self):
        self.approve()
        before = s.read_case(**self.staff())
        repeated = self.intake("a")
        self.assertEqual(repeated["case_id"], self.a["case_id"])

        independent = CaseDeliveryFixture()
        independent.setUp()
        self.assertNotEqual(independent.a["case_id"], self.a["case_id"])
        self.assertEqual(independent.intake("a")["case_id"], independent.a["case_id"])
        self.assertEqual(s.read_case(**self.staff()), before)
        self.assertEqual(s.read_case(**independent.staff())["revision"], 1)

    def test_journey_binds_human_answer_all_signed_parts_and_private_case(self):
        b = self.intake("b")
        approved = self.approve()
        self.assertFalse(self.status()["delivery_verified"])
        result = self.stage()
        self.assertEqual(result["status"], "STAGED_NOT_SENT")
        self.assertGreater(result["part_count"], 1)
        segments = []
        lease = self.reserve()
        segments.append(
            d.resolve_case_delivery_text(
                **self.staff(),
                lease=lease,
                verify_receipt=self.approval_verifier,
            ).exact_text
        )
        self.record(lease, self.event(lease, reported="ACCEPTED"))
        self.assertFalse(self.status()["delivery_verified"])
        self.assertEqual(self.status()["verified_parts"], 0)
        self.record(lease)
        self.assertFalse(self.status()["delivery_verified"])
        while lease := self.reserve():
            segments.append(
                d.resolve_case_delivery_text(
                    **self.staff(),
                    lease=lease,
                    verify_receipt=self.approval_verifier,
                ).exact_text
            )
            self.record(lease)
        self.assertEqual("".join(segments), approved["answers"][-1]["text"])
        before = list(DeliveryAuditEvent.objects.values())
        status = self.status()
        self.assertTrue(status["delivery_verified"])
        self.assertFalse(status["read_confirmed"])
        self.assertEqual(status["delivery_status"], "PROVIDER_REPORTED_DELIVERY_VERIFIED")
        self.assertFalse(self.status(b)["delivery_verified"])
        self.assertEqual(before, list(DeliveryAuditEvent.objects.values()))
        for secret in (
            b["public_ref"],
            self.a["case_id"],
            self.a["token"],
            approved["answers"][-1]["text"],
            result["plan_sha256"],
            "signature_b64url",
        ):
            self.assertNotIn(secret, str(status))

    def test_scholarly_approval_and_explicit_split_required_before_return(self):
        with self.assertRaises(s.CaseConflict):
            self.request()
        self.approve()
        with self.assertRaises(ValueError):
            d.prepare_case_delivery(**self.staff(), max_chars=24, split=False)
        with self.assertRaises(queue.QueueConflict):
            self.stage(verify_receipt=lambda receipt: True)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_wrong_signed_case_facts_answer_plan_or_mufti_cannot_stage(self):
        self.approve()
        request = self.request()
        for change in (
            {"case_key": "foreign-case"},
            {"source_digest": "a" * 64},
            {"reply_digest": "b" * 64},
            {"answer_sha256": "c" * 64},
            {"answer_revision": 2},
            {"plan_sha256": "d" * 64},
            {"approver_id": "another-mufti"},
            {"approver_role": "ORGANIZER_ADMIN"},
        ):
            with self.subTest(change=change), self.assertRaises((s.CaseConflict, InvalidPlan)):
                self.stage(receipt=self.receipt(request, **change))
        self.assertEqual(CaseDelivery.objects.count(), 0)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_tampered_expired_or_revoked_mufti_signature_does_not_stage(self):
        self.approve()
        request = self.request()
        for receipt in (
            replace(self.receipt(request), signature_b64url="x" * 86),
            self.receipt(request, expires_at=(self.now - timedelta(seconds=1)).isoformat()),
        ):
            with self.assertRaises(InvalidPlan):
                self.stage(receipt=receipt)
        self.revoked = True
        with self.assertRaises(InvalidPlan):
            self.stage()
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_same_receipt_is_idempotent_and_replacement_is_rejected(self):
        self.approve()
        receipt = self.receipt(self.request())
        first = self.stage(receipt=receipt)
        before = list(DeliveryAuditEvent.objects.values())
        self.assertEqual(first, self.stage(receipt=receipt))
        self.assertEqual(before, list(DeliveryAuditEvent.objects.values()))
        with self.assertRaisesRegex(s.CaseConflict, "already_bound"):
            self.stage()
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(CaseDelivery.objects.count(), 1)

    def test_bridge_failure_rolls_back_claim_manifest_context_and_audit(self):
        self.approve()
        with patch.object(
            CaseDelivery.objects, "create", side_effect=RuntimeError("synthetic-fault")
        ):
            with self.assertRaises(RuntimeError):
                self.stage()
        for model in (
            CaseDelivery,
            ApprovalClaim,
            DeliveryIntent,
            SignedDeliveryContext,
            DeliveryAuditEvent,
        ):
            self.assertEqual(model.objects.count(), 0)
        self.stage()

    def test_cross_case_signed_event_and_lease_are_rejected(self):
        b = self.intake("b")
        self.directory.refs = frozenset([self.a["public_ref"], b["public_ref"]])
        for case in (self.a, b):
            self.approve(case)
            self.stage(case)
        a_lease, b_lease = self.reserve(), self.reserve(b)
        with self.assertRaises(s.CaseConflict):
            self.record(a_lease, case=b)
        with self.assertRaises(queue.QueueConflict):
            self.record(b_lease, self.event(a_lease))
        with self.assertRaises(queue.QueueConflict):
            d.resolve_case_delivery_text(
                **self.staff(b),
                lease=a_lease,
                verify_receipt=self.approval_verifier,
            )
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_wrong_part_attempt_or_signature_never_records_evidence(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        for event in (
            self.event(lease, part_digest="a" * 64),
            self.event(lease, attempt_sha256="b" * 64),
            replace(self.event(lease), signature_b64url="x" * 86),
        ):
            with self.assertRaises(queue.QueueConflict):
                self.record(lease, event)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)

    def test_followup_invalidates_old_plan_receipt_reservation_and_projection(self):
        approved = self.approve()
        receipt = self.receipt(self.request())
        self.stage(receipt=receipt)
        lease = self.reserve()
        s.add_followup(
            token=self.a["token"],
            text="واقعة جديدة اصطناعية",
            expected_revision=approved["revision"],
            synthetic_fixtures_only=True,
        )
        for operation in (
            lambda: self.stage(receipt=receipt),
            self.reserve,
            lambda: self.record(lease),
            lambda: d.resolve_case_delivery_text(
                **self.staff(),
                lease=lease,
                verify_receipt=self.approval_verifier,
            ),
        ):
            with self.assertRaises(s.CaseConflict):
                operation()
        self.assertFalse(self.status()["delivery_verified"])
        self.assertEqual(CaseDelivery.objects.count(), 1)
        self.approve()
        with self.assertRaises(InvalidPlan):
            self.stage(receipt=receipt)
        self.stage()
        self.assertEqual(CaseDelivery.objects.count(), 2)
        with self.assertRaises(s.CaseConflict):
            self.record(lease)
        self.deliver()
        self.assertTrue(self.status()["delivery_verified"])

    def test_new_answer_or_clarification_hides_previous_complete_evidence(self):
        self.approve()
        self.stage()
        self.deliver()
        self.assertTrue(self.status()["delivery_verified"])
        current = s.read_case(**self.staff())
        s.request_clarification(
            **self.staff(),
            text="استيضاح اصطناعي",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        self.assertFalse(self.status()["delivery_verified"])
        self.approve()
        self.assertEqual(self.status()["delivery_status"], "NOT_STAGED")
        self.assertFalse(self.status()["delivery_verified"])

    def test_unsigned_legacy_callbacks_do_not_count_as_delivery_proof(self):
        self.approve()
        self.stage()
        while lease := self.reserve():
            queue.record_receipt(
                lease=lease,
                receipt_reference="legacy-" + secrets.token_hex(8),
                provider_message_id="legacy-message",
                reported="DELIVERED",
                verify_provider_receipt=lambda _: True,
            )
        self.assertFalse(self.status()["delivery_verified"])
        self.assertEqual(self.status()["delivery_status"], "PROVIDER_EVIDENCE_INCOMPLETE")

    def test_missing_revoked_or_unavailable_provider_verifier_fails_closed(self):
        self.approve()
        self.stage()
        self.deliver()
        self.assertTrue(self.status()["delivery_verified"])
        for verifier in (
            None,
            lambda _: True,
            self.verifier(revoked_key_ids=frozenset({"channel-key"})),
            self.verifier(is_key_revoked=lambda _: (_ for _ in ()).throw(RuntimeError())),
        ):
            with self.subTest(verifier=type(verifier).__name__):
                self.assertFalse(self.status(verifier=verifier)["delivery_verified"])

    def test_scoped_identity_and_epoch_required_for_preparation_and_reservation(self):
        self.approve()
        self.stage()
        for directory in (
            TestDirectory(["foreign-case"]),
            TestDirectory([self.a["public_ref"]], role="ORGANIZER_ADMIN"),
            TestDirectory([self.a["public_ref"]], epoch="epoch-2"),
        ):
            with self.assertRaises(s.CaseConflict):
                d.prepare_case_delivery(**self.staff(provider=directory))
            with self.assertRaises(s.CaseConflict):
                self.reserve(provider=directory)
        with self.assertRaises(queue.QueueConflict):
            self.reserve(verify_worker=lambda *_: False)
        self.revoked = True
        with self.assertRaises(queue.QueueConflict):
            self.reserve()
        self.assertFalse(DeliveryIntent.objects.exclude(state="STAGED").exists())

    def test_access_rotation_revocation_and_expiry_do_not_leak_proof(self):
        self.approve()
        self.stage()
        self.deliver()
        rotated = s.rotate_access(**self.staff(), requester_id="requester-a")
        with self.assertRaises(s.CaseConflict):
            self.status()
        self.a["token"] = rotated["token"]
        self.assertTrue(self.status()["delivery_verified"])
        with patch.object(s.timezone, "now", return_value=timezone.now() + timedelta(days=8)):
            with self.assertRaises(s.CaseConflict):
                self.status()
        s.revoke_access(**self.staff(), requester_id="requester-a")
        with self.assertRaises(s.CaseConflict):
            self.status()

    def test_bridge_is_immutable_and_database_rejects_cross_case_binding(self):
        self.approve()
        self.stage()
        b = self.intake("b")
        self.directory.refs |= frozenset([b["public_ref"]])
        self.approve(b)
        b_decision = CaseDecision.objects.get(case_id=b["case_id"])
        for action in (
            lambda: CaseDelivery.objects.update(max_chars=50),
            lambda: CaseDelivery.objects.all().delete(),
            lambda: CaseDelivery.objects.create(
                decision=b_decision,
                approval=ApprovalClaim.objects.get(),
                max_chars=24,
                split=True,
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()
        self.assertEqual(CaseDelivery.objects.count(), 1)

    def test_concurrent_duplicate_staging_creates_one_binding_and_manifest(self):
        self.approve()
        receipt = self.receipt(self.request())

        def stage(_):
            connections.close_all()
            try:
                return self.stage(receipt=receipt)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(stage, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(CaseDelivery.objects.count(), 1)
        self.assertEqual(ApprovalClaim.objects.count(), 1)

    def test_guard_migration_preserves_populated_bindings_and_signed_evidence(self):
        self.approve()
        self.stage()
        self.deliver()
        models = (
            CaseDelivery,
            ApprovalClaim,
            DeliveryIntent,
            ProviderReceipt,
            ProviderSignatureEvidence,
        )
        before = [list(model.objects.order_by("pk").values()) for model in models]
        try:
            call_command("migrate", "casework", "0003", interactive=False, verbosity=0)
            self.assertEqual(
                before, [list(model.objects.order_by("pk").values()) for model in models]
            )
        finally:
            # Reversing casework also reverses dependent apps; restore the
            # complete current graph before any current service reads it.
            call_command("migrate", interactive=False, verbosity=0)
        self.assertEqual(before, [list(model.objects.order_by("pk").values()) for model in models])
        self.assertTrue(self.status()["delivery_verified"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseDelivery.objects.update(split=False)

    def test_synthetic_ack_required_and_preparation_does_not_write(self):
        self.approve()
        before = list(DeliveryAuditEvent.objects.values())
        self.request()
        self.assertEqual(before, list(DeliveryAuditEvent.objects.values()))
        self.assertEqual(CaseDelivery.objects.count(), 0)
        with self.assertRaises(s.CaseConflict):
            d.prepare_case_delivery(**{**self.staff(), "synthetic_fixtures_only": False})
        with self.assertRaises(s.CaseConflict):
            d.requester_delivery_status(self.a["token"], verifier=self.channel_verifier)

    def test_queue_guard_rejects_arbitrary_transactions_and_expired_context(self):
        with transaction.atomic(), self.assertRaises(queue.QueueConflict):
            with queue.synthetic_queue_atomic():
                self.fail("unguarded caller transaction accepted")
        with queue.synthetic_queue_atomic():
            context = copy_context()
            queue._postgres_only()
        with self.assertRaisesRegex(queue.QueueConflict, "owned_queue_transaction_changed"):
            context.run(queue._postgres_only)
        with transaction.atomic(), self.assertRaises(queue.QueueConflict):
            queue._postgres_only()
        # A fresh service call must still perform its ordinary preflight.
        with patch.object(
            queue, "require_synthetic_write", side_effect=queue.SyntheticWriteDenied("TEST_DENIED")
        ):
            with self.assertRaises(queue.QueueConflict):
                self.request()

    def test_queue_unit_rechecks_configuration_and_connection_identity(self):
        import os

        with queue.synthetic_queue_atomic():
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                with self.assertRaises(queue.QueueConflict):
                    queue._postgres_only()
            raw = connection.connection
            try:
                connection.connection = object()
                with self.assertRaisesRegex(queue.QueueConflict, "owned_queue_transaction_changed"):
                    queue._postgres_only()
            finally:
                connection.connection = raw

    def test_identity_epoch_changed_inside_commit_rejects_every_write(self):
        self.approve()
        receipt = self.receipt(self.request())
        original = self.directory.resolve
        calls = 0

        def changed(subject):
            nonlocal calls
            calls += 1
            if calls >= 3:
                self.directory.epoch = "epoch-revoked"
            return original(subject)

        with patch.object(self.directory, "resolve", side_effect=changed):
            with self.assertRaises(queue.QueueConflict):
                self.stage(receipt=receipt)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(CaseDelivery.objects.count(), 0)

    def test_staging_waits_for_followup_then_rejects_the_old_approval(self):
        approved = self.approve()
        receipt = self.receipt(self.request())
        followup_locked, staging_started, release = Event(), Event(), Event()
        original_event, original_resolve = s._event, self.directory.resolve

        def held_event(case, action, *args, **kwargs):
            result = original_event(case, action, *args, **kwargs)
            if action == "FOLLOWUP":
                followup_locked.set()
                if not release.wait(10):
                    raise RuntimeError("synthetic-race-timeout")
            return result

        def resolve(subject):
            staging_started.set()
            return original_resolve(subject)

        def followup():
            connections.close_all()
            try:
                return s.add_followup(
                    token=self.a["token"],
                    text="واقعة متزامنة اصطناعية",
                    expected_revision=approved["revision"],
                    synthetic_fixtures_only=True,
                )
            finally:
                connections.close_all()

        def stage():
            connections.close_all()
            try:
                return self.stage(receipt=receipt)
            finally:
                connections.close_all()

        with (
            patch.object(s, "_event", side_effect=held_event),
            patch.object(
                self.directory,
                "resolve",
                side_effect=resolve,
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(followup)
            try:
                self.assertTrue(followup_locked.wait(10))
                second = pool.submit(stage)
                self.assertTrue(staging_started.wait(10))
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10)["status"], "UNDER_REVIEW")
            with self.assertRaises(s.CaseConflict):
                second.result(timeout=10)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(CaseDelivery.objects.count(), 0)

    def test_historical_signature_stays_verifiable_without_resend_or_read_claim(self):
        self.approve()
        self.stage()
        self.deliver()
        before = list(ProviderSignatureEvidence.objects.order_by("pk").values())
        self.now += timedelta(days=1)
        self.assertTrue(self.status()["delivery_verified"])
        self.assertFalse(self.status()["read_confirmed"])
        self.assertEqual(before, list(ProviderSignatureEvidence.objects.order_by("pk").values()))

    def test_epoch_change_during_signature_verification_rolls_back_staging(self):
        self.approve()
        receipt = self.receipt(self.request())
        original = self.approval_verifier._identity_lookup

        def revoke_epoch(subject):
            self.directory.epoch = "epoch-changed-during-signature"
            return original(subject)

        with patch.object(self.approval_verifier, "_identity_lookup", side_effect=revoke_epoch):
            with self.assertRaises((queue.QueueConflict, s.CaseConflict)):
                self.stage(receipt=receipt)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(CaseDelivery.objects.count(), 0)

    def test_provider_audit_failure_rolls_back_receipt_and_case_projection(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        before = list(DeliveryAuditEvent.objects.order_by("pk").values())
        with patch.object(queue, "_audit", side_effect=RuntimeError("synthetic-audit-failure")):
            with self.assertRaises(RuntimeError):
                self.record(lease)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(before, list(DeliveryAuditEvent.objects.order_by("pk").values()))
        self.assertFalse(self.status()["delivery_verified"])
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")
