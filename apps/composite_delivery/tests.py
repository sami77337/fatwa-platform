"""Focused PostgreSQL contracts using synthetic cases and offline signing fixtures."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.tests import audio_fixture
from apps.casework import services as cases
from apps.casework.models import CaseDelivery
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryAttempt,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
)
from tests.casework.delivery_fixtures import CaseDeliveryFixture

from . import services as composite
from .models import CompositeDelivery
from .simulator import OfflineProviderSimulator


@override_settings(FATWA_COMPOSITE_DELIVERY_ENABLED=True, FATWA_ANSWER_MEDIA_ENABLED=True)
class CompositeTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )
        configured = override_settings(FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile)
        configured.enable()
        self.addCleanup(configured.disable)
        self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        self.channel_verifier = self.simulator.verifier

    def save(self, case=None):
        current = cases.read_case(**self.staff(case))
        return media.save_multipart_answer(
            **self.staff(case),
            text="جواب بشري مركب اصطناعي",
            files=[
                {"raw": b"synthetic file", "filename": "answer.txt", "media_type": "text/plain"},
                audio_fixture(),
            ],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )

    def approve(self, case=None):
        current = self.save(case)
        return cases.record_decision(
            **self.staff(case),
            answer_id=current["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )

    def request(self, case=None):
        return composite.prepare_composite_delivery(**self.staff(case))

    def stage(self, case=None, receipt=None, **changes):
        return composite.stage_composite_delivery(
            **{
                **self.staff(case),
                "receipt": receipt or self.receipt(self.request(case)),
                "verify_receipt": self.approval_verifier,
                **changes,
            }
        )

    def reserve(self, case=None, **changes):
        return composite.reserve_composite_part(
            **{
                **self.staff(case),
                "worker_id": "synthetic-worker",
                "verify_worker": lambda worker, plan: worker == "synthetic-worker",
                "verify_receipt": self.approval_verifier,
                **changes,
            }
        )

    def resolve(self, lease, case=None):
        return composite.resolve_composite_part(
            **self.staff(case),
            lease=lease,
            verify_receipt=self.approval_verifier,
        )

    def record(self, lease, event=None, case=None):
        return composite.record_composite_event(
            **self.staff(case),
            lease=lease,
            event=event,
            verifier=self.channel_verifier,
        )

    def status(self, case=None):
        return composite.composite_status(**self.staff(case), verifier=self.channel_verifier)

    def outcome(self, lease, part, reported):
        event = self.simulator.event(lease=lease, part=part, reported=reported)
        self.record(lease, event)
        return event

    def test_text_file_audio_signed_full_journey_and_accepted_is_not_delivered(self):
        self.approve()
        request = self.request()
        self.assertEqual([p["kind"] for p in request["parts"]], ["TEXT", "FILE", "AUDIO"])
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        receipt = self.receipt(request)
        self.assertEqual(self.stage(receipt=receipt), self.stage(receipt=receipt))
        self.assertEqual(DeliveryIntent.objects.count(), 3)
        self.assertEqual(CaseDelivery.objects.count(), 0)
        seen = []
        while lease := self.reserve():
            part = self.resolve(lease)
            seen.append(part["id"])
            self.outcome(lease, part, "ACCEPTED")
            self.assertFalse(self.status()["delivery_verified"])
            self.outcome(lease, part, "DELIVERED")
        self.assertEqual(seen, [p["id"] for p in request["parts"]])
        status = self.status()
        self.assertTrue(status["delivery_verified"])
        self.assertEqual(status["verified_parts"], 3)
        self.assertFalse(status["read_confirmed"])
        self.assertFalse(status["human_action"])
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 6)
        self.assertEqual(DeliveryAttempt.objects.count(), 3)
        self.assertEqual(self.stage(receipt=receipt)["status"], "ALREADY_RECORDED")
        self.assertIsNone(self.reserve())

    def test_capability_kind_mime_size_text_and_receipt_gaps_block_entire_staging(self):
        self.approve()
        baseline = self.profile
        for profile in (
            replace(
                baseline, capabilities=replace(baseline.capabilities, supported=frozenset({"text"}))
            ),
            replace(baseline, allowed_mime=frozenset({"application/pdf"})),
            replace(baseline, max_media_bytes=2),
            replace(baseline, capabilities=replace(baseline.capabilities, max_text_chars=2)),
            replace(baseline, capabilities=replace(baseline.capabilities, delivery_receipts=False)),
        ):
            with self.subTest(profile=profile):
                self.profile = profile
                request = self.request()
                self.assertEqual(len(request["parts"]), 3)
                self.assertEqual(request["plan"]["status"], "REQUIRES_HUMAN_DECISION")
                with self.assertRaises(queue.QueueConflict):
                    self.stage()
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.assertEqual(CompositeDelivery.objects.count(), 0)

    @override_settings(FATWA_ANSWER_LINKS_ENABLED=True)
    def test_explicit_link_capability_is_required_and_exact_authored_url_is_resolved(self):
        self.directory.projection_epoch = lambda: repr((self.directory.refs, self.directory.role, self.directory.epoch))
        original = "https://youtu.be/aB3dE6gH9_k"
        draft = media.save_multipart_answer(**self.staff(), text="نص مع رابط اختاره المفتي",
            files=[], links=[{"url": original, "label": "مرجع فيديو اصطناعي"}],
            expected_revision=1, expected_evidence_version=1)
        cases.record_decision(**self.staff(), answer_id=draft["answers"][-1]["id"],
            action="APPROVE", expected_revision=draft["revision"], expected_evidence_version=1)
        self.assertEqual(self.request()["plan"]["status"], "REQUIRES_HUMAN_DECISION")
        with self.assertRaises(queue.QueueConflict):
            self.stage()
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.profile = replace(self.profile,
            capabilities=replace(self.profile.capabilities, supported=self.profile.capabilities.supported | {"link"}),
            allowed_mime=self.profile.allowed_mime | {"text/uri-list"})
        self.stage()
        first = self.reserve()
        self.outcome(first, self.resolve(first), "DELIVERED")
        link_lease = self.reserve()
        resolved = self.resolve(link_lease)
        self.assertEqual(resolved["kind"], "YOUTUBE_LINK")
        self.assertEqual(resolved["raw"], original.encode())
        self.assertEqual(resolved["metadata"]["availability"], "UNVERIFIED")
        self.outcome(link_lease, resolved, "DELIVERED")
        self.assertTrue(self.status()["delivery_verified"])
        self.assertIsNone(self.reserve())

    def test_failure_partial_uncertainty_never_retries_completed_or_failed_parts(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "DELIVERED")
        self.assertEqual(self.status()["state"], "PARTIALLY_DELIVERED")
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "FAILED")
        self.assertEqual(self.status()["state"], "PARTIALLY_FAILED")
        unknown = self.reserve()
        part = self.resolve(unknown)
        queue.quarantine_expired_leases(now=timezone.now() + timedelta(minutes=2))
        status = self.status()
        self.assertEqual(status["state"], "NEEDS_RECONCILIATION")
        self.assertTrue(status["human_action"])
        self.assertFalse(status["delivery_verified"])
        self.assertIsNone(self.reserve())
        self.assertEqual(DeliveryAttempt.objects.count(), 3)
        self.outcome(unknown, part, "DELIVERED")
        self.assertEqual(self.status()["state"], "PARTIALLY_FAILED")
        self.assertIsNone(self.reserve())
        self.assertTrue(all(not p["automatic_retry"] for p in self.status()["parts"]))

    def test_wrong_part_ordinal_hash_attempt_plan_signature_and_replay(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        event = self.simulator.event(lease=lease, part=part, reported="DELIVERED")
        second = self.reserve()
        # Valid signature for another leased part is still rejected.
        with self.assertRaises(queue.QueueConflict):
            self.record(second, event)
        for changed in (
            replace(event, ordinal=2),
            replace(event, part_digest="a" * 64),
            replace(event, attempt_sha256="b" * 64),
            replace(event, signature_b64url="x" * 86),
            replace(event, plan_fingerprint="c" * 64),
        ):
            with self.assertRaises(ValueError):
                self.record(lease, changed)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.record(lease, event)
        self.record(lease, event)
        self.assertEqual(ProviderReceipt.objects.count(), 1)
        self.assertEqual(self.status()["verified_parts"], 1)

    def test_current_approval_signature_and_human_authority_required(self):
        with self.assertRaises(cases.CaseConflict):
            self.request()
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.request()
        self.approve()
        request = self.request()
        for receipt in (
            replace(self.receipt(request), signature_b64url="x" * 86),
            self.receipt(request, approver_id="another-mufti"),
            self.receipt(request, answer_sha256="a" * 64),
            self.receipt(request, approver_role="ORGANIZER_ADMIN"),
        ):
            with self.assertRaises(ValueError):
                self.stage(receipt=receipt)
        with self.assertRaises(queue.QueueConflict):
            self.stage(verify_receipt=lambda _: True)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.directory.role = "ORGANIZER_ADMIN"
        with self.assertRaises(cases.CaseConflict):
            self.request()

    def test_capability_drift_same_version_blocks_old_signature_and_reserved_content(self):
        self.approve()
        receipt = self.receipt(self.request())
        baseline = self.profile
        self.profile = replace(baseline, max_media_bytes=191999)
        with self.assertRaises(ValueError):
            self.stage(receipt=receipt)
        self.profile = baseline
        self.stage(receipt=receipt)
        lease = self.reserve()
        part = self.resolve(lease)
        event = self.simulator.event(lease=lease, part=part, reported="DELIVERED")
        self.profile = replace(baseline, max_media_bytes=191999)
        for operation in (
            self.reserve,
            lambda: self.resolve(lease),
            lambda: self.record(lease, event),
            self.status,
        ):
            with self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_new_facts_and_answer_close_current_delivery_without_erasing_history(self):
        approved = self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        event = self.simulator.event(lease=lease, part=part, reported="DELIVERED")
        cases.add_followup(
            token=self.a["token"],
            text="وقائع جديدة اصطناعية",
            expected_revision=approved["revision"],
            synthetic_fixtures_only=True,
        )
        for operation in (
            self.reserve,
            lambda: self.resolve(lease),
            lambda: self.record(lease, event),
            self.status,
        ):
            with self.assertRaises(cases.CaseConflict):
                operation()
        self.approve()
        self.stage()
        with self.assertRaises(cases.CaseConflict):
            self.record(lease, event)
        self.assertEqual(CompositeDelivery.objects.count(), 2)
        self.assertEqual(DeliveryIntent.objects.count(), 6)
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.reserve()

    def test_cross_case_leases_and_receipts_are_rejected(self):
        b = self.intake("b")
        self.directory.refs = frozenset([self.a["public_ref"], b["public_ref"]])
        for case in (self.a, b):
            self.approve(case)
            self.stage(case)
        lease = self.reserve()
        part = self.resolve(lease)
        event = self.simulator.event(lease=lease, part=part, reported="DELIVERED")
        with self.assertRaises(queue.QueueConflict):
            self.resolve(lease, b)
        with self.assertRaises(cases.CaseConflict):
            self.record(lease, event, b)
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_epoch_scope_flag_and_production_gate_are_rechecked(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        self.directory.epoch = "revoked-epoch"
        with self.assertRaises(cases.CaseConflict):
            self.resolve(lease)
        self.directory.epoch = "epoch-1"
        self.directory.refs = frozenset()
        with self.assertRaises(cases.CaseConflict):
            self.reserve()
        self.directory.refs = frozenset([self.a["public_ref"]])
        with override_settings(FATWA_COMPOSITE_DELIVERY_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.request()
        with patch.dict("os.environ", {"FATWA_PRODUCTION": "1"}):
            with self.assertRaises(cases.CaseConflict):
                self.request()
        with self.assertRaises(cases.CaseConflict):
            composite.prepare_composite_delivery(
                **{**self.staff(), "synthetic_fixtures_only": False}
            )

    def test_binding_failure_rolls_back_queue_and_immutable_binding_rejects_changes(self):
        self.approve()
        with patch.object(
            CompositeDelivery.objects, "create", side_effect=RuntimeError("fixture-fault")
        ):
            with self.assertRaises(RuntimeError):
                self.stage()
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.stage()
        for operation in (
            lambda: CompositeDelivery.objects.update(capability_sha256="a" * 64),
            lambda: CompositeDelivery.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        with self.assertRaisesRegex(cases.CaseConflict, "already_bound"):
            self.stage()

    def test_unsigned_queue_success_never_becomes_verified_composite_delivery(self):
        self.approve()
        self.stage()
        while lease := self.reserve():
            queue.record_receipt(
                lease=lease,
                receipt_reference="unsigned-" + lease.intent_key,
                provider_message_id="unsigned-message",
                reported="DELIVERED",
                verify_provider_receipt=lambda _: True,
            )
            self.assertTrue(self.status()["human_action"])
        status = self.status()
        self.assertFalse(status["delivery_verified"])
        self.assertTrue(all(p["human_action"] for p in status["parts"]))
        self.assertEqual(status["evidence_status"], "PROVIDER_EVIDENCE_INCOMPLETE")
        self.assertTrue(status["human_action"])

    def test_populated_binding_guard_migration_reversal_and_restore(self):
        self.approve()
        self.stage()
        original = list(CompositeDelivery.objects.values())
        try:
            call_command("migrate", "composite_delivery", "0001", verbosity=0)
        finally:
            call_command("migrate", "composite_delivery", verbosity=0)
        self.assertEqual(original, list(CompositeDelivery.objects.values()))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CompositeDelivery.objects.update(manifest_sha256="a" * 64)
        self.assertIsNotNone(self.reserve())

    def test_storage_reader_preserves_exact_bytes_and_rejects_changed_payload(self):
        self.approve()
        self.stage()
        self.reserve()  # text
        lease = self.reserve()  # file
        original = self.resolve(lease)
        self.assertEqual(original["raw"], b"synthetic file")
        with patch.object(media, "staff_read", return_value={**original, "raw": b"changed"}):
            with self.assertRaisesRegex(cases.CaseConflict, "content_changed"):
                self.resolve(lease)
        with patch.object(
            media, "staff_read", side_effect=cases.CaseConflict("storage_unavailable")
        ):
            with self.assertRaises(cases.CaseConflict):
                self.resolve(lease)
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_simulator_refuses_foreign_part_and_forged_self_consistent_content(self):
        from hashlib import sha256

        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        for changed in (
            {**part, "id": "00000000-0000-0000-0000-000000000000"},
            {**part, "raw": b"forged", "sha256": sha256(b"forged").hexdigest(), "size": 6},
        ):
            with self.assertRaises(queue.QueueConflict):
                self.simulator.event(lease=lease, part=changed, reported="DELIVERED")
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_post_verification_scope_revocation_rolls_back_signed_provider_event(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        event = self.simulator.event(lease=lease, part=part, reported="DELIVERED")
        real = composite.record_signed_provider_event

        def revoke_after_record(**kwargs):
            result = real(**kwargs)
            self.directory.refs = frozenset()
            return result

        with patch.object(
            composite, "record_signed_provider_event", side_effect=revoke_after_record
        ):
            with self.assertRaises(cases.CaseConflict):
                self.record(lease, event)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.get(pk=lease.intent_key).state, "LEASED")

    def test_binding_scope_guard_rejects_other_case_and_rolls_back_plan(self):
        self.approve()
        other = self.intake("other")
        self.directory.refs = frozenset([self.a["public_ref"], other["public_ref"]])
        approved = self.approve(other)
        from apps.casework.models import CaseDecision

        wrong = CaseDecision.objects.get(answer_id=approved["approved_answer_id"])
        create = CompositeDelivery.objects.create

        def wrong_case(**kwargs):
            return create(**{**kwargs, "decision": wrong})

        with patch.object(CompositeDelivery.objects, "create", side_effect=wrong_case):
            with self.assertRaises(IntegrityError):
                self.stage()
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(CompositeDelivery.objects.count(), 0)

    def test_scoped_timeout_reconciliation_and_arabic_status_projection(self):
        from django.template.loader import render_to_string

        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        self.outcome(lease, part, "ACCEPTED")
        html = render_to_string("composite_delivery/status.html", {"status": self.status()})
        self.assertIn("قبول المزود فقط؛ التسليم غير مؤكد", html)
        self.assertNotIn("اكتمل تقرير التسليم", html)
        expired = self.reserve()
        with patch.object(
            queue.timezone, "now", return_value=timezone.now() + timedelta(minutes=2)
        ):
            result = composite.reconcile_composite_timeouts(**self.staff())
        self.assertEqual(result, {"unresolved_parts": 1, "automatic_retry": False})
        self.assertEqual(
            DeliveryIntent.objects.get(pk=expired.intent_key).state,
            "UNKNOWN_REQUIRES_RECONCILIATION",
        )
        html = render_to_string("composite_delivery/status.html", {"status": self.status()})
        self.assertIn("نتيجة غير محسومة", html)
        self.assertIn("لا إعادة إرسال تلقائية", html)
