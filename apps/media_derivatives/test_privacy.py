"""Actual classified original + scanner + technical job processing, without a DB-held decoder."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.data_privacy import services as privacy
from apps.data_privacy import test_support as privacy_fixtures
from apps.data_privacy.catalog import locate

from . import execution, services
from .models import DerivedOutput
from .test_support import FEATURES, DerivativeFixture


@override_settings(**FEATURES)
class DerivativePrivacyTests(DerivativeFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.derivative_authority = self.authority
        self.authority = privacy_fixtures.Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True, FATWA_DATA_PRIVACY_AUTHORITY=self.authority
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.target = locate("CASE", self.receipt["case_id"])
        self.child = locate("ATTACHMENT", self.attachment["id"])
        for target in (self.target, self.child):
            self.allow(target, "CONFIDENTIAL", "CLASSIFY")
            privacy.classify(
                kind=target.kind,
                identifier=target.identifier,
                level="CONFIDENTIAL",
                note="تصنيف مستقل لمصدر اصطناعي",
                expected_digest=privacy.ZERO,
                expected_source_digest=target.source_digest,
                request_key=uuid.uuid4(),
                provider=self.directory,
                subject_id="editor",
                synthetic_fixtures_only=True,
            )
            key = self.allow(target, "CONFIDENTIAL", "READ")
            if target == self.child:
                self.child_key = key

    allow = privacy_fixtures.PrivacyFixture.allow

    def principal(self):
        return privacy.staff_principal(self.directory, self.directory.resolve("editor"))

    def test_actual_classified_child_and_scan_are_independent_from_ready_derivative(self):
        job = self.prepare()
        actual = execution.FFmpegProcessor.run
        calls = []

        def decode(processor, *args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            calls.append(True)
            return actual(processor, *args, **kwargs)

        with patch.object(execution.FFmpegProcessor, "run", decode):
            self.assertEqual(self.execute(job)["state"], "READY")
        self.assertTrue(calls)
        del self.authority.grants[self.child_key]
        with self.assertRaises(cases.CaseConflict):
            services.read_output(**self.common, job_id=job["id"])
        self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")
        self.scanner.current = replace(
            self.scanner.current, signature_version="SYNTHETIC-revoked-classified-source"
        )
        with self.assertRaises(cases.CaseConflict):
            services.read_output(**self.common, job_id=job["id"])

    def test_privacy_revoked_after_actual_decoder_blocks_commit_without_rewriting_original(self):
        job = self.prepare()
        actual = execution.FFmpegProcessor.run

        def decode(processor, *args, **kwargs):
            result = actual(processor, *args, **kwargs)
            del self.authority.grants[self.child_key]
            return result

        with (
            patch.object(execution.FFmpegProcessor, "run", decode),
            self.assertRaises(cases.CaseConflict),
        ):
            self.execute(job)
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")
        self.assertEqual(services.original(**self.common, job_id=job["id"])["raw"], self.raw)
