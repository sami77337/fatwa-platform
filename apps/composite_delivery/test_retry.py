"""Real PostgreSQL bounded retries, exact ancestry, native forms and revocation."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlencode

from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt, DeliveryIntent
from apps.experimental_publication.tests_ui import fields
from tests.casework.test_http import post

from . import retries, services, views
from . import test_selection as selection
from . import tests as contracts
from .models import CompositeDelivery, CompositeRetry
from .test_desk import SETTINGS, DeskFixture

FEATURES = {
    **SETTINGS,
    "FATWA_COMPOSITE_RETRY_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


class RetryFixture(DeskFixture):
    record = contracts.CompositeTests.record
    outcome = contracts.CompositeTests.outcome
    status = contracts.CompositeTests.status

    def setUp(self):
        super().setUp()
        self.directory.projection_epoch = lambda: repr(
            (
                self.directory.provider_id,
                self.directory.refs,
                self.directory.role,
                self.directory.epoch,
            )
        )
        self.approve()
        self.stage()

    def failed(self, number=2):
        failed = None
        for ordinal in (1, 2, 3):
            lease = self.reserve()
            part = self.resolve(lease)
            self.outcome(lease, part, "FAILED" if ordinal == number else "DELIVERED")
            if ordinal == number:
                failed = (lease, part)
        return failed

    def retry_request(self, parent, request_id=None):
        return retries.prepare_retry(
            **self.staff(), parent_intent=parent.intent_key, request_id=request_id or uuid.uuid4()
        )

    def retry_receipt(self, request, **changes):
        self.now = timezone.now()
        return self.receipt(request, **changes)

    def retry_stage(self, request, receipt=None):
        return retries.stage_retry(
            **self.staff(),
            parent_intent=request["retry"]["parent_intent"],
            request_id=request["retry"]["request_id"],
            receipt=receipt or self.retry_receipt(request),
            verify_receipt=self.approval_verifier,
        )


@override_settings(**FEATURES)
class RetryTests(RetryFixture, TransactionTestCase):
    def test_fresh_signed_successor_keeps_logical_ordinal_exact_bytes_and_original_failure(self):
        parent, original = self.failed()
        failed = DeliveryIntent.objects.get(pk=parent.intent_key)
        before = list(DeliveryIntent.objects.order_by("pk").values())
        attempts = list(DeliveryAttempt.objects.order_by("pk").values())
        request = self.retry_request(parent)
        self.assertEqual(request["retry"]["logical_ordinal"], 2)
        self.assertEqual(request["retry"]["queue_ordinal"], 1)
        self.assertEqual(len(request["retry"]["full_manifest"]), 3)
        self.assertEqual(
            request["retry"]["part"], {key: original[key] for key in request["retry"]["part"]}
        )
        old = adapter._load_context(CompositeDelivery.objects.get().approval)[0]
        with self.assertRaises(ValueError):
            self.retry_stage(request, old)
        receipt = self.retry_receipt(request)
        first = self.retry_stage(request, receipt)
        self.assertEqual(first, self.retry_stage(request, receipt))
        self.assertEqual(CompositeRetry.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), 4)
        self.assertEqual(self.status()["verified_parts"], 2)
        lease = self.reserve()
        part = self.resolve(lease)
        self.assertEqual((part["ordinal"], part["queue_ordinal"]), (2, 1))
        self.assertEqual(part["raw"], original["raw"])
        self.assertEqual(part["id"], original["id"])
        with self.assertRaises(queue.QueueConflict):
            self.simulator.event(
                lease=lease, part={**part, "queue_ordinal": 2}, reported="DELIVERED"
            )
        self.outcome(lease, part, "ACCEPTED")
        self.assertFalse(self.status()["delivery_verified"])
        self.assertIsNone(self.reserve())
        self.outcome(lease, part, "DELIVERED")
        result = self.status()
        self.assertTrue(result["delivery_verified"])
        self.assertEqual(result["verified_parts"], 3)
        self.assertEqual(result["original_plan"]["state"], "PARTIALLY_FAILED")
        self.assertFalse(result["original_plan"]["delivery_verified"])
        self.assertEqual(queue.summarize_plan(failed.plan_fingerprint).state, "PARTIALLY_FAILED")
        self.assertFalse(result["read_confirmed"])
        self.assertIsNone(self.reserve())
        self.assertEqual(
            before,
            list(
                DeliveryIntent.objects.filter(pk__in=[r["intent_key"] for r in before])
                .order_by("pk")
                .values()
            ),
        )
        self.assertEqual(
            attempts,
            list(
                DeliveryAttempt.objects.filter(pk__in=[r["intent_id"] for r in attempts])
                .order_by("pk")
                .values()
            ),
        )

    def test_never_retries_staged_leased_accepted_delivered_or_unknown_parts(self):
        row = DeliveryIntent.objects.order_by("ordinal").first()
        for state in ("STAGED", "LEASED", "SENT_UNCONFIRMED", "DELIVERED"):
            if state == "LEASED":
                lease = self.reserve()
                part = self.resolve(lease)
            elif state == "SENT_UNCONFIRMED":
                self.outcome(lease, part, "ACCEPTED")
            elif state == "DELIVERED":
                self.outcome(lease, part, "DELIVERED")
            with (
                self.subTest(state=state),
                self.assertRaisesMessage(cases.CaseConflict, "requires_failed_part"),
            ):
                retries.prepare_retry(**self.staff(), parent_intent=row.pk, request_id=uuid.uuid4())
        lease = self.reserve()
        queue.quarantine_expired_leases(now=timezone.now() + timedelta(minutes=2))
        with self.assertRaisesMessage(cases.CaseConflict, "requires_failed_part"):
            self.retry_request(lease)
        self.assertEqual(CompositeRetry.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 3)

    def test_three_retries_are_bounded_and_every_failed_successor_needs_fresh_approval(self):
        parent, _ = self.failed(3)
        for number in range(1, 4):
            request = self.retry_request(parent)
            self.assertEqual(request["retry"]["retry_number"], number)
            self.retry_stage(request)
            parent = self.reserve()
            part = self.resolve(parent)
            self.assertEqual((part["ordinal"], part["queue_ordinal"]), (3, 1))
            self.outcome(parent, part, "FAILED")
        with self.assertRaisesMessage(cases.CaseConflict, "limit_reached"):
            self.retry_request(parent)
        self.assertEqual(CompositeRetry.objects.count(), 3)
        self.assertEqual(DeliveryAttempt.objects.count(), 6)
        self.assertIsNone(self.reserve())
        self.assertFalse(self.status()["parts"][2]["may_retry"])

    def test_unsigned_failure_wrong_signature_old_approval_and_changed_context_are_rejected(self):
        parent = self.reserve()
        queue.record_receipt(
            lease=parent,
            receipt_reference="unsigned-failure",
            provider_message_id="unsigned",
            reported="FAILED",
            verify_provider_receipt=lambda _: True,
        )
        with self.assertRaisesMessage(cases.CaseConflict, "signed_failure_required"):
            self.retry_request(parent)
        signed = self.reserve()
        self.outcome(signed, self.resolve(signed), "FAILED")
        request = self.retry_request(signed)
        receipt = self.retry_receipt(request)
        for changed in (
            replace(receipt, signature_b64url="x" * 86),
            replace(receipt, issued_at="2026-11-21T12:00:00"),
            self.retry_receipt(request, issued_at=(self.now - timedelta(minutes=1)).isoformat()),
            self.retry_receipt(request, approver_id="different-mufti"),
        ):
            with self.assertRaises(ValueError):
                self.retry_stage(request, changed)
        for value in (False, 1):
            with (
                override_settings(FATWA_COMPOSITE_RETRY_ENABLED=value),
                self.assertRaises(cases.CaseConflict),
            ):
                self.retry_stage(request, receipt)
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.retry_stage(request, receipt)
        with (
            override_settings(FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=None),
            self.assertRaisesMessage(cases.CaseConflict, "current_approval_verifier_required"),
        ):
            self.retry_stage(request, receipt)
        self.profile = replace(self.profile, max_media_bytes=191999)
        with self.assertRaises(cases.CaseConflict):
            self.retry_stage(request, receipt)
        self.assertEqual(CompositeRetry.objects.count(), 0)
        self.assertEqual(ApprovalClaim.objects.count(), 1)

    def test_concurrent_exact_request_is_one_successor_and_different_request_cannot_fork(self):
        parent, _ = self.failed()
        request = self.retry_request(parent)
        receipt = self.retry_receipt(request)
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait()
                return self.retry_stage(request, receipt)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(CompositeRetry.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), 4)
        with self.assertRaisesMessage(cases.CaseConflict, "parent_already_bound"):
            self.retry_request(parent)

    def test_late_identity_revocation_rolls_back_signed_claim_intent_and_retry_binding(self):
        parent, _ = self.failed()
        request = self.retry_request(parent)
        receipt = self.retry_receipt(request)
        original = adapter.commit_signed_approved_plan

        def revoke(**kwargs):
            result = original(**kwargs)
            self.directory.refs = frozenset()
            return result

        with (
            patch.object(adapter, "commit_signed_approved_plan", side_effect=revoke),
            self.assertRaises(ValueError),
        ):
            self.retry_stage(request, receipt)
        self.assertEqual(CompositeRetry.objects.count(), 0)
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), 3)

        self.assertTrue(queue.verify_audit_chain())

    def test_sql_history_immutability_resealed_wrong_part_and_populated_migration_guards(self):
        parent, _ = self.failed()
        self.retry_stage(self.retry_request(parent))
        row = CompositeRetry.objects.get()
        before = list(CompositeRetry.objects.values())
        for sql, params in (
            ("UPDATE composite_delivery_compositeretry SET retry_number=2 WHERE id=%s", [row.pk]),
            ("DELETE FROM composite_delivery_compositeretry WHERE id=%s", [row.pk]),
            (
                "UPDATE fatwa_delivery_intent SET state='STAGED' WHERE intent_key=%s",
                [parent.intent_key],
            ),
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, params)
        clone = CompositeRetry.objects.get()
        clone.pk = uuid.uuid4()
        clone.scope = {
            **clone.scope,
            "request_id": str(clone.pk),
            "logical_ordinal": 3,
            "part": self.request()["parts"][2],
        }
        clone.logical_ordinal = 3
        clone.part_id = clone.scope["part"]["id"]
        clone.canonical_payload = queue._canonical(clone.scope).decode()
        clone.sha256 = services._hash(clone.scope)
        with self.assertRaises(DatabaseError), transaction.atomic():
            clone.save(force_insert=True)
        try:
            call_command("migrate", "composite_delivery", "0004", verbosity=0)
            call_command("migrate", "composite_delivery", verbosity=0)
            with self.assertRaises(DatabaseError):
                call_command("migrate", "composite_delivery", "0003", verbosity=0)
        finally:
            call_command("migrate", "composite_delivery", verbosity=0)
        self.assertEqual(before, list(CompositeRetry.objects.values()))
        with self.assertRaises(DatabaseError), transaction.atomic():
            CompositeRetry.objects.filter(pk=row.pk).delete()


@override_settings(**FEATURES)
class RetryHTTPTests(RetryFixture, TransactionTestCase):
    def test_native_export_fresh_signed_retry_and_exact_provider_receipt_preserve_failed_history(
        self,
    ):
        parent, _ = self.failed(3)
        page = self.open(self.login())
        exported = post(
            self.client, "/casework/staff/", fields(page, "composite_retry_export"), page
        )
        self.assertEqual(exported.status_code, 200, exported.content)
        request = json.loads(exported.content)
        signed = json.dumps(
            {
                "request_sha256": request["plan_sha256"],
                "receipt": asdict(self.retry_receipt(request)),
            }
        )
        data = {**fields(page, "composite_retry_stage"), "confirm": "yes", "response_json": signed}
        self.assertEqual(
            self.client.post(
                "/casework/staff/",
                urlencode(
                    {key: value for key, value in data.items() if key != "csrfmiddlewaretoken"}
                ),
                content_type="application/x-www-form-urlencoded",
            ).status_code,
            403,
        )
        response = post(self.client, "/casework/staff/", data, page)
        self.assertEqual(response.status_code, 200, response.content)
        replay = post(self.client, "/casework/staff/", data, page)
        self.assertEqual(replay.status_code, 200)
        lease = self.reserve()
        part = self.resolve(lease)
        self.assertEqual((part["ordinal"], part["queue_ordinal"]), (3, 1))
        response = self.open(response)
        response = self.action(
            response,
            "composite_receipt",
            part_id=part["id"],
            confirm="yes",
            response_json=self.bundle(lease, part, "DELIVERED"),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, "PARTIALLY_FAILED")
        self.assertContains(response, "اكتمل تقرير التسليم")
        self.assertNotContains(response, "data-retry-export=")
        self.assertNotContains(response, lease.token)
        self.assertEqual(
            DeliveryIntent.objects.get(pk=parent.intent_key).state, "FAILED_REQUIRES_REVIEW"
        )
        self.assertEqual(DeliveryAttempt.objects.count(), 4)

    def test_late_native_render_revocation_rolls_back_new_retry_and_hides_old_content(self):
        parent, _ = self.failed()
        page = self.open(self.login())
        exported = post(
            self.client, "/casework/staff/", fields(page, "composite_retry_export"), page
        )
        request = json.loads(exported.content)
        data = {
            **fields(page, "composite_retry_stage"),
            "confirm": "yes",
            "response_json": json.dumps(
                {
                    "request_sha256": request["plan_sha256"],
                    "receipt": asdict(self.retry_receipt(request)),
                }
            ),
        }
        render = views.render

        def revoke(*args, **kwargs):
            result = render(*args, **kwargs)
            self.directory.refs = frozenset()
            return result

        with patch.object(views, "render", side_effect=revoke):
            result = post(self.client, "/casework/staff/", data, page)
        self.assertEqual(result.status_code, 409)
        self.assertNotContains(result, parent.intent_key, status_code=409)
        self.assertEqual(CompositeRetry.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 3)


@override_settings(**{**FEATURES, "FATWA_COMPOSITE_CHOICES_ENABLED": True})
class SelectedRetryTests(selection.SelectionFixture, TransactionTestCase):
    def test_native_selected_plan_and_retry_keep_omitted_originals_out_of_every_attempt(self):
        page = self.open(self.login())
        page = post(
            self.client,
            "/casework/staff/",
            {**fields(page, "composite_choice"), "confirm": "yes"},
            page,
        )
        self.assertEqual(page.status_code, 200)
        exported = post(self.client, "/casework/staff/", fields(page, "composite_export"), page)
        request = json.loads(exported.content)
        page = post(
            self.client,
            "/casework/staff/",
            {
                **fields(page, "composite_stage"),
                "confirm": "yes",
                "response_json": json.dumps(
                    {
                        "request_sha256": request["plan_sha256"],
                        "receipt": asdict(self.receipt(request)),
                    }
                ),
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        lease = self.reserve()
        part = self.resolve(lease)
        services.record_composite_event(
            **self.staff(),
            lease=lease,
            event=self.simulator.event(lease=lease, part=part, reported="FAILED"),
            verifier=self.channel_verifier,
        )
        proposed = retries.prepare_retry(
            **self.staff(), parent_intent=lease.intent_key, request_id=uuid.uuid4()
        )
        self.assertEqual(proposed["retry"]["selection_mode"], "TEXT_ONLY")
        self.assertEqual(len(proposed["retry"]["full_manifest"]), 3)
        self.now = timezone.now()
        retries.stage_retry(
            **self.staff(),
            parent_intent=lease.intent_key,
            request_id=proposed["retry"]["request_id"],
            receipt=self.receipt(proposed),
            verify_receipt=self.approval_verifier,
        )
        lease = self.reserve()
        retried = self.resolve(lease)
        self.assertEqual(retried["kind"], "TEXT")
        self.assertEqual(retried["raw"], part["raw"])
        services.record_composite_event(
            **self.staff(),
            lease=lease,
            event=self.simulator.event(lease=lease, part=retried, reported="DELIVERED"),
            verifier=self.channel_verifier,
        )
        result = services.composite_status(**self.staff(), verifier=self.channel_verifier)
        self.assertTrue(result["delivery_verified"])
        self.assertEqual(result["expected_parts"], 1)
        self.assertEqual(result["original_plan"]["state"], "FAILED_REQUIRES_REVIEW")
        self.assertEqual(DeliveryAttempt.objects.count(), 2)
        self.assertTrue(queue.verify_audit_chain())
