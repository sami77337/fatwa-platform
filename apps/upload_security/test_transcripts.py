"""Seventh campaign upload: actual case-bound reviewed transcript bundle."""

from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvidence
from apps.fast8_transcript_queue.workbench.services import _read_archive
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links import tests as transcript_fixtures
from apps.transcript_case_links.models import TranscriptLink, TranscriptUpload

from . import services
from .models import QuarantinedFile, UploadAdmission
from .test_support import ScanFixture


class TranscriptUploadAdmissionTests(ScanFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.bundle = transcript_fixtures.bundle()
        self.common = transcript_fixtures.common(self.receipt)

    def preview(self):
        return transcripts.preview(**self.common, bundle=self.bundle)

    def test_blocked_or_unauthorized_bundle_cannot_reach_transcript_reconstruction(self):
        self.common["provider"].refs = frozenset()
        with patch.object(transcripts, "restore_bundle") as parser:
            with self.assertRaises(cases.CaseConflict):
                self.preview()
            parser.assert_not_called()
        self.assertFalse(QuarantinedFile.objects.exists())
        self.common["provider"].refs = frozenset({self.receipt["public_ref"]})
        self.scanner.changes = {"status": "BLOCKED"}
        with patch.object(transcripts, "restore_bundle") as parser:
            with self.assertRaises(cases.CaseConflict):
                self.preview()
            parser.assert_not_called()
        self.assertFalse(TranscriptUpload.objects.exists())

    def test_current_member_receipts_precede_preview_and_exact_question_attachment(self):
        invoke = services.invoke

        def engine(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            return invoke(*args, **kwargs)

        with patch.object(services, "invoke", side_effect=engine):
            preview = self.preview()
            attached = transcript_fixtures.attach(self.receipt, preview)
        expected = {
            sha256(raw).hexdigest() for raw in [self.bundle, *_read_archive(self.bundle).values()]
        }
        self.assertEqual(set(QuarantinedFile.objects.values_list("pk", flat=True)), expected)
        self.assertEqual(len(self.scanner.calls), len(expected))
        self.assertEqual(
            set(UploadAdmission.objects.values_list("purpose", flat=True)), {"TRANSCRIPT_BUNDLE"}
        )
        self.assertTrue(attached["created"])
        self.assertEqual(bytes(TranscriptUpload.objects.get().bundle), self.bundle)
        self.assertEqual(
            CaseEvidence.objects.get(version=2).text, preview["entries"][0].question.text
        )
        self.assertFalse(AnswerRevision.objects.exists())

    def test_changed_scan_snapshot_blocks_source_read_and_attachment_without_erasing_original(self):
        preview = self.preview()
        originals = list(TranscriptUpload.objects.values())
        self.scanner.current = replace(self.scanner.current, engine_version="SYNTHETIC-changed")
        with self.assertRaises(cases.CaseConflict):
            transcript_fixtures.attach(self.receipt, preview)
        self.assertFalse(TranscriptLink.objects.exists())
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertEqual(list(TranscriptUpload.objects.values()), originals)
