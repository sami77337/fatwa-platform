"""Actual domain upload/read paths; only the malware provider is SYNTHETIC."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments import tests as attachment_fixtures
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvidence, CaseSource
from apps.material_import import formats, test_formats
from apps.material_import import services as imports
from apps.material_import import tests as import_fixtures
from apps.material_import.models import ImportBatch
from apps.precise_citations import integration as citation_scopes
from apps.requester_portal import services as portal
from apps.research_library import public as public_library
from apps.research_library import services as library
from apps.research_library import test_support as library_fixtures
from apps.research_library.models import LibraryBlob, LibraryVersion
from apps.source_case_intake import services as intake
from apps.source_case_intake import simulators
from apps.source_case_intake.models import AttachmentBinding, SourceReceipt
from tests.casework import test_core as identities

from . import services
from .models import QuarantinedFile, ScanAttempt
from .test_support import RAW, ScanFixture, ScannerMixin


def origins():
    return (
        list(Case.objects.order_by("pk").values()),
        list(CaseEvidence.objects.order_by("pk").values()),
        list(CaseSource.objects.order_by("pk").values()),
    )


@override_settings(
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_REQUESTER_PORTAL_ENABLED=True,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_ANSWER_MEDIA_ENABLED=True,
)
class DomainUploadAdmissionTests(ScanFixture, TransactionTestCase):
    def upload(self, **changes):
        return attachment_fixtures.upload(self.receipt, raw=RAW, **changes)

    def reply(self):
        return portal.submit_reply(
            token=self.receipt["token"],
            text="رد بشري أصلي مع مرفق",
            expected_revision=1,
            attachment={"raw": RAW, "filename": "reply.txt", "media_type": "text/plain"},
            synthetic_fixtures_only=True,
        )

    def test_clean_scan_precedes_parser_and_keeps_scanner_outside_database_locks(self):
        invoke, validate = services.invoke, attachments.validate

        def engine(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(QuarantinedFile.objects.count(), 1)
            self.assertEqual(CaseAttachment.objects.count(), 0)
            return invoke(*args, **kwargs)

        def parser(*args, **kwargs):
            self.assertEqual(ScanAttempt.objects.get().status, "CLEAN")
            return validate(*args, **kwargs)

        with (
            patch.object(services, "invoke", side_effect=engine),
            patch.object(attachments, "validate", side_effect=parser),
        ):
            result = self.upload()
        self.assertEqual(bytes(CaseAttachment.objects.get().original), RAW)
        self.assertEqual(
            attachments.requester_read(
                token=self.receipt["token"],
                attachment_id=result["id"],
                synthetic_fixtures_only=True,
            )["raw"],
            RAW,
        )
        self.assertEqual(len(self.scanner.calls), 1)

    def test_blocked_reply_keeps_both_text_and_attachment_out_of_case_and_retry_cannot_release(
        self,
    ):
        before = origins()
        self.scanner.changes = {"status": "BLOCKED"}
        with self.assertRaises(services.UploadSecurityDenied):
            self.reply()
        self.assertEqual(origins(), before)
        self.assertFalse(CaseAttachment.objects.exists())
        self.assertEqual(bytes(QuarantinedFile.objects.get().original), RAW)
        self.scanner.changes = {}
        with self.assertRaises(services.UploadSecurityDenied):
            self.upload(filename="renamed.txt")
        self.assertEqual(len(self.scanner.calls), 1)

    def test_unauthorized_or_stale_request_never_quarantines_or_parses_input(self):
        for changes in ({"token": "invalid"}, {"expected_revision": 9}):
            with self.subTest(changes=changes), patch.object(attachments, "validate") as parser:
                with self.assertRaises(cases.CaseConflict):
                    self.upload(**changes)
                parser.assert_not_called()
        self.assertFalse(QuarantinedFile.objects.exists())
        self.assertEqual(self.scanner.calls, [])

    def test_clean_receipt_does_not_bypass_original_type_or_structural_checks(self):
        before = origins()
        with self.assertRaises(cases.CaseConflict):
            self.upload(filename="unsafe.html", media_type="text/html")
        self.assertEqual(ScanAttempt.objects.get().status, "CLEAN")
        self.assertEqual(origins(), before)
        self.assertFalse(CaseAttachment.objects.exists())

    def test_late_scanner_change_rolls_back_the_whole_reply_after_owner_creation(self):
        before = origins()
        metadata = attachments._metadata

        def late(row):
            result = metadata(row)
            self.scanner.current = replace(self.scanner.current, engine_version="SYNTHETIC-revoked")
            return result

        with patch.object(attachments, "_metadata", side_effect=late):
            with self.assertRaises(services.UploadSecurityDenied):
                self.reply()
        self.assertEqual(origins(), before)
        self.assertFalse(CaseAttachment.objects.exists())
        self.assertEqual(ScanAttempt.objects.get().status, "CLEAN")

    def test_successful_reply_scans_once_and_commits_both_evidence_records(self):
        result = self.reply()
        self.assertEqual(result["evidence_version"], 3)
        self.assertEqual(CaseAttachment.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.filter(kind="FOLLOWUP").count(), 2)
        self.assertEqual(len(self.scanner.calls), 1)

    def test_expired_or_disabled_scan_gate_blocks_original_and_list_without_rewriting(self):
        result = self.upload()
        original = list(CaseAttachment.objects.values())
        with patch.object(
            services.timezone, "now", return_value=timezone.now() + timedelta(hours=1)
        ):
            with self.assertRaises(cases.CaseConflict):
                attachments.requester_read(
                    token=self.receipt["token"],
                    attachment_id=result["id"],
                    synthetic_fixtures_only=True,
                )
        with override_settings(FATWA_UPLOAD_SECURITY_ENABLED=False):
            with self.assertRaises(services.UploadSecurityDenied):
                attachments.requester_list(
                    token=self.receipt["token"], synthetic_fixtures_only=True
                )
        self.assertEqual(list(CaseAttachment.objects.values()), original)

    def source(self):
        return intake.ingest(
            raw=simulators.telegram(document=True),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )

    def attach_source(self, source, **changes):
        return intake.attach_fixture(
            **{
                "receipt_id": source["receipt_id"],
                "source_file_id": "synthetic-file-1",
                "token": source["token"],
                "raw": RAW,
                "filename": "source.txt",
                "media_type": "text/plain",
                "synthetic_fixtures_only": True,
                **changes,
            }
        )

    def test_source_attachment_authorizes_exact_declaration_and_preserves_raw_receipt(self):
        source = self.source()
        original = list(SourceReceipt.objects.values())
        with self.assertRaises(intake.IntakeError):
            self.attach_source(source, source_file_id="not-declared")
        self.assertEqual(self.scanner.calls, [])
        saved = self.attach_source(source)
        self.assertTrue(saved["created"])
        self.assertFalse(self.attach_source(source)["created"])
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(list(SourceReceipt.objects.values()), original)
        self.assertEqual(AttachmentBinding.objects.count(), 1)

    def test_blocked_source_attachment_does_not_bind_or_add_case_evidence(self):
        source = self.source()
        before = origins(), list(SourceReceipt.objects.values())
        self.scanner.changes = {"status": "BLOCKED"}
        with self.assertRaises(cases.CaseConflict):
            self.attach_source(source)
        self.assertEqual((origins(), list(SourceReceipt.objects.values())), before)
        self.assertFalse(AttachmentBinding.objects.exists())

    def answer(self, directory=None):
        return answers.save_multipart_answer(
            **attachment_fixtures.staff_common(self.receipt, directory),
            text="تحرير بشري محفوظ",
            files=[{"raw": RAW, "filename": "answer.txt", "media_type": "text/plain"}],
            expected_revision=1,
            expected_evidence_version=1,
        )

    def test_answer_scans_only_uploaded_part_and_keeps_human_text_original(self):
        self.answer()
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(
            bytes(AnswerPart.objects.get(ordinal=1).original), "تحرير بشري محفوظ".encode()
        )
        self.assertEqual(bytes(AnswerPart.objects.get(ordinal=2).original), RAW)
        self.assertEqual(QuarantinedFile.objects.count(), 1)
        self.assertEqual(QuarantinedFile.objects.get().pk, sha256(RAW).hexdigest())

    def test_staff_scope_revoked_while_scanning_prevents_any_answer_or_part(self):
        directory = identities.TestDirectory([self.receipt["public_ref"]])
        before = origins()
        self.scanner.hook = lambda: setattr(directory, "refs", frozenset())
        with self.assertRaises(cases.CaseConflict):
            self.answer(directory)
        self.assertEqual(origins(), before)
        self.assertFalse(AnswerRevision.objects.exists())
        self.assertFalse(AnswerPart.objects.exists())

    def test_last_citation_callback_cannot_release_approval_after_scanner_revocation(self):
        saved = self.answer()
        before = origins()
        original = cases._staff
        scanner = self.scanner

        class LateGuard:
            libraries = {}

            def callbacks(self):
                scanner.current = replace(scanner.current, engine_version="SYNTHETIC-late")

            def verify_bytes(self):
                pass

            def final_pins(self, **kwargs):
                pass

        def inject(case):
            result = original(case)
            citation_scopes._USES.get()[-1].append(LateGuard())
            return result

        with patch.object(cases, "_staff", side_effect=inject):
            with self.assertRaises(services.UploadSecurityDenied):
                cases.record_decision(
                    **attachment_fixtures.staff_common(self.receipt),
                    answer_id=saved["answers"][-1]["id"],
                    action="APPROVE",
                    expected_revision=2,
                    expected_evidence_version=1,
                )
        self.assertEqual(origins(), before)
        self.assertFalse(CaseDecision.objects.exists())


@override_settings(**library_fixtures.FEATURES)
class LibraryUploadAdmissionTests(
    ScannerMixin, library_fixtures.LibraryFixture, TransactionTestCase
):
    def file(self, **changes):
        return self.write(file_bytes=RAW, filename="source.txt", media_type="text/plain", **changes)

    def test_real_edit_permission_is_required_before_scan_or_parser(self):
        self.authority.denied.add("EDIT")
        with patch.object(library, "validate_file") as parser:
            with self.assertRaises(cases.CaseConflict):
                self.file()
            parser.assert_not_called()
        self.assertFalse(QuarantinedFile.objects.exists())
        self.assertEqual(self.scanner.calls, [])

    def test_library_original_and_metadata_recheck_current_scan_receipt(self):
        row = self.file()
        self.assertEqual(bytes(LibraryBlob.objects.get().original), RAW)
        approved = self.approve(row)
        self.assertEqual(
            library.file_content(**self.common, version_id=approved["version_id"])["raw"], RAW
        )
        self.scanner.current = replace(
            self.scanner.current, signature_version="SYNTHETIC-new-signatures"
        )
        for operation in (
            lambda: library.read_material(**self.common, version_id=row["version_id"]),
            lambda: library.file_content(**self.common, version_id=row["version_id"]),
        ):
            with self.assertRaises(services.UploadSecurityDenied):
                operation()
        self.assertEqual(bytes(LibraryBlob.objects.get().original), RAW)

    def test_late_library_authorizer_cannot_commit_after_scan_configuration_changes(self):
        def revoke(values):
            if LibraryVersion.objects.exists():
                self.scanner.current = replace(
                    self.scanner.current, engine_version="SYNTHETIC-late"
                )

        self.authority.hook = revoke
        with self.assertRaises(services.UploadSecurityDenied):
            self.file()
        self.assertFalse(LibraryVersion.objects.exists())
        self.assertFalse(LibraryBlob.objects.exists())
        self.assertEqual(bytes(QuarantinedFile.objects.get().original), RAW)

    def test_public_metadata_and_content_hide_a_released_file_with_stale_scan(self):
        row = self.release(self.file())
        with public_library.public_projection() as current:
            self.assertIn(row["version_id"], current.records)
        self.scanner.current = replace(self.scanner.current, engine_version="SYNTHETIC-stale")
        with public_library.public_projection() as current:
            self.assertEqual(current.records, {})


@override_settings(**import_fixtures.FEATURES)
class ImportUploadAdmissionTests(ScannerMixin, import_fixtures.ImportFixture, TransactionTestCase):
    def bundle(self):
        if not hasattr(self, "_bundle"):
            self._bundle = test_formats.archive(
                [import_fixtures.source_row(file_member="files/one.txt")],
                [("files/one.txt", "one.txt", "text/plain", RAW)],
            )
        return self._bundle

    def stage_bundle(self):
        import uuid

        return imports.stage(
            **self.common,
            raw=self.bundle(),
            filename="source.zip",
            namespace="synthetic-import",
            provenance="اصطناعي",
            rights_basis="اختبار فقط",
            request_key=uuid.uuid4(),
            expected_revision=1,
            expected_evidence_version=1,
        )

    def test_denied_stage_and_blocked_envelope_do_not_reach_archive_parser(self):
        self.import_authority.denied.add("STAGE")
        with patch.object(formats, "parse") as parser:
            with self.assertRaises(cases.CaseConflict):
                self.stage_bundle()
            parser.assert_not_called()
        self.assertFalse(QuarantinedFile.objects.exists())
        self.import_authority.denied.clear()
        self.scanner.changes = {"status": "BLOCKED"}
        with patch.object(formats, "parse") as parser:
            with self.assertRaises(cases.CaseConflict):
                self.stage_bundle()
            parser.assert_not_called()
        self.assertFalse(ImportBatch.objects.exists())

    def test_manifest_file_requires_its_own_receipt_before_any_import_batch_is_saved(self):
        self.scanner.hook = lambda: (
            self.scanner.changes.update(status="BLOCKED")
            if self.scanner.calls[-1].raw == RAW
            else None
        )
        with self.assertRaises(services.UploadSecurityDenied):
            self.stage_bundle()
        self.assertEqual(len(self.scanner.calls), 2)
        self.assertEqual(ScanAttempt.objects.get(file_id=sha256(RAW).hexdigest()).status, "BLOCKED")
        self.assertEqual(QuarantinedFile.objects.count(), 2)
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(LibraryVersion.objects.exists())

    def test_group_apply_reuses_exact_receipts_without_scanning_under_transaction(self):
        invoke = services.invoke

        def engine(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            return invoke(*args, **kwargs)

        with patch.object(services, "invoke", side_effect=engine):
            batch = self.stage_bundle()
            planned = self.plan(self.configure(batch))
            result = self.apply(self.review(planned))
        self.assertEqual(result["state"], "APPLIED")
        self.assertEqual(len(self.scanner.calls), 2)
        self.assertEqual(bytes(LibraryBlob.objects.get().original), RAW)
        self.assertEqual(bytes(ImportBatch.objects.get().raw), self.bundle())
