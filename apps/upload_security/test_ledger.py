"""Real PostgreSQL quarantine/receipt invariants and bounded untrusted adapter results."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from threading import Event
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_attachments.models import CaseAttachment
from apps.casework.models import Case, CaseEvidence
from apps.delivery_queue.services import synthetic_queue_atomic

from . import execution, services
from .models import QuarantinedFile, ScanAttempt, UploadAdmission
from .test_support import RAW, ScanFixture


class UploadScanLedgerTests(ScanFixture, TransactionTestCase):
    def test_missing_real_or_synthetic_scanner_retains_bytes_without_release(self):
        for values in (
            {"FATWA_UPLOAD_SCANNER": None},
            {"FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC": False},
        ):
            with self.subTest(values=values), override_settings(**values):
                with self.assertRaises(services.UploadSecurityDenied):
                    self.prepare()
        self.assertEqual(bytes(QuarantinedFile.objects.get().original), RAW)
        self.assertEqual(ScanAttempt.objects.get().status, "UNAVAILABLE")
        self.assertEqual(UploadAdmission.objects.count(), 1)
        self.assertEqual(self.scanner.calls, [])
        self.assertEqual(CaseAttachment.objects.count(), 0)

    def test_complete_exact_receipt_is_idempotent_and_does_not_write_domain_records(self):
        original = list(Case.objects.values()), list(CaseEvidence.objects.values())
        first = self.prepare()
        self.assertEqual(self.prepare(), first)
        self.assertEqual(first["mode"], "SYNTHETIC")
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(UploadAdmission.objects.count(), 1)
        self.assertEqual(ScanAttempt.objects.count(), 1)
        self.assertEqual(
            (list(Case.objects.values()), list(CaseEvidence.objects.values())), original
        )
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(services.require(sha256(RAW).hexdigest(), len(RAW)), first)

    def test_blocked_bytes_cannot_be_released_by_retry_or_changed_scanner(self):
        self.scanner.changes = {"status": "BLOCKED"}
        with self.assertRaises(services.UploadSecurityDenied):
            self.prepare()
        self.scanner.changes.clear()
        self.scanner.current = replace(self.scanner.current, engine_version="SYNTHETIC-engine-v2")
        for _ in range(2):
            with self.assertRaises(services.UploadSecurityDenied):
                self.prepare()
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(ScanAttempt.objects.count(), 1)
        self.assertEqual(ScanAttempt.objects.get().status, "BLOCKED")

    def test_incomplete_wrong_source_or_unloaded_signatures_are_not_clean(self):
        for index, change in enumerate(
            (
                {"complete": False},
                {"scanned_files": 0},
                {"scanned_files": True},
                {"loaded_signatures": 0},
                {"sha256": "0" * 64},
                {"size": True},
                {"spec": replace(self.scanner.current, signature_version="SYNTHETIC-other")},
            )
        ):
            self.scanner.changes = change
            raw = RAW + str(index).encode()
            with self.subTest(change=change), self.assertRaises(services.UploadSecurityDenied):
                self.prepare(raw)
        self.assertFalse(ScanAttempt.objects.filter(status="CLEAN").exists())
        self.assertEqual(ScanAttempt.objects.count(), 7)

    def test_scanner_change_during_work_is_a_revoked_outcome_not_a_release(self):
        self.scanner.hook = lambda: setattr(
            self.scanner, "current", replace(self.scanner.current, engine_version="SYNTHETIC-v2")
        )
        with self.assertRaises(services.UploadSecurityDenied):
            self.prepare()
        self.assertEqual(ScanAttempt.objects.get().status, "REVOKED")

    def test_expiry_missing_policy_disabled_feature_and_late_change_deny_saved_receipts(self):
        self.prepare()
        identifier = sha256(RAW).hexdigest()
        for values in (
            {"FATWA_UPLOAD_SECURITY_ENABLED": False},
            {"FATWA_UPLOAD_SCAN_POLICY": None},
            {"FATWA_UPLOAD_SCANNER": None},
        ):
            with self.subTest(values=values), override_settings(**values):
                with self.assertRaises(services.UploadSecurityDenied):
                    services.require(identifier, len(RAW))
        future = timezone.now() + timedelta(minutes=10)
        with patch.object(services.timezone, "now", return_value=future):
            with self.assertRaises(services.UploadSecurityDenied):
                services.require(identifier, len(RAW))
        with self.assertRaises(services.UploadSecurityDenied):
            with services.projection():
                services.require(identifier, len(RAW))
                self.scanner.current = replace(self.scanner.current, engine_version="SYNTHETIC-v2")

    def test_unprepared_scan_cannot_start_inside_an_owned_domain_transaction(self):
        with synthetic_queue_atomic():
            with self.assertRaisesRegex(services.UploadSecurityDenied, "preflight_required"):
                self.prepare()
        self.assertEqual(QuarantinedFile.objects.count(), 0)
        self.assertEqual(self.scanner.calls, [])
        self.prepare()
        with synthetic_queue_atomic():
            self.prepare()
        self.assertEqual(len(self.scanner.calls), 1)

    def test_timeout_keeps_the_single_slot_and_discards_all_late_output(self):
        started, release = Event(), Event()
        self.scanner.hook = lambda: (started.set(), release.wait(2))
        try:
            with override_settings(
                FATWA_UPLOAD_SCAN_POLICY=replace(self.policy, timeout_seconds=0.02)
            ):
                with self.assertRaises(services.UploadSecurityDenied):
                    self.prepare()
                self.assertTrue(started.is_set())
                with self.assertRaises(services.UploadSecurityDenied):
                    self.prepare(RAW + b"another")
            self.assertEqual(
                sorted(ScanAttempt.objects.values_list("status", flat=True)), ["BUSY", "TIMED_OUT"]
            )
            self.assertEqual(len(self.scanner.calls), 1)
        finally:
            release.set()
            self.assertTrue(execution.SLOT.acquire(timeout=2))
            execution.SLOT.release()
        self.assertFalse(ScanAttempt.objects.filter(status="CLEAN").exists())
        self.assertEqual(ScanAttempt.objects.count(), 2)

    def test_sql_mutation_false_coverage_and_forged_predecessor_are_rejected(self):
        self.prepare()
        for model, field, value in (
            (QuarantinedFile, "original", b"changed"),
            (UploadAdmission, "subject_id", "other"),
            (ScanAttempt, "complete", False),
        ):
            with self.subTest(model=model), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.update(**{field: value})
            with (
                self.subTest(delete=model),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM " + connection.ops.quote_name(model._meta.db_table))
        old = ScanAttempt.objects.get()
        for change in ({"complete": False}, {"previous_digest": "0" * 64}):
            fields = services.body(old)
            fields.pop("id")
            fields.update(sequence=2, previous_digest=old.digest, valid_until=old.valid_until)
            fields.update(change)
            with (
                self.subTest(change=change),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                services.seal(ScanAttempt(**fields))
