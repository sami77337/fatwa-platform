"""Actual original-file failures recorded before the upload-security gate exists."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments import tests as attachment_fixtures
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence


@override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
class MissingScannerAdmissionTests(TransactionTestCase):
    def test_enabled_missing_scanner_cannot_create_a_canonical_attachment(self):
        receipt = attachment_fixtures.new_case()
        before = list(Case.objects.values()), list(CaseEvidence.objects.values())
        with override_settings(
            FATWA_UPLOAD_SECURITY_ENABLED=True,
            FATWA_UPLOAD_SCAN_POLICY=None,
            FATWA_UPLOAD_SCANNER=None,
        ):
            with self.assertRaises(cases.CaseConflict):
                attachment_fixtures.upload(receipt)
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual((list(Case.objects.values()), list(CaseEvidence.objects.values())), before)

    def test_enabled_unscanned_file_never_reaches_the_existing_parser(self):
        receipt = attachment_fixtures.new_case()
        with (
            override_settings(
                FATWA_UPLOAD_SECURITY_ENABLED=True,
                FATWA_UPLOAD_SCAN_POLICY=None,
                FATWA_UPLOAD_SCANNER=None,
            ),
            patch.object(attachments, "validate", wraps=attachments.validate) as parser,
        ):
            try:
                attachment_fixtures.upload(receipt)
            except cases.CaseConflict:
                pass
            self.assertEqual(parser.call_count, 0)
        self.assertEqual(CaseAttachment.objects.count(), 0)

    def test_enabled_legacy_unscanned_original_is_not_a_read_capability(self):
        receipt = attachment_fixtures.new_case()
        row = attachment_fixtures.upload(receipt)
        original = list(CaseAttachment.objects.values())
        with override_settings(
            FATWA_UPLOAD_SECURITY_ENABLED=True,
            FATWA_UPLOAD_SCAN_POLICY=None,
            FATWA_UPLOAD_SCANNER=None,
        ):
            with self.assertRaises(cases.CaseConflict):
                attachments.requester_read(
                    token=receipt["token"],
                    attachment_id=row["id"],
                    synthetic_fixtures_only=True,
                )
        self.assertEqual(list(CaseAttachment.objects.values()), original)
