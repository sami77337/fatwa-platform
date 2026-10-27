"""Explicit synthetic PG acceptance; not collected by offline test_*.py discovery."""

import os
from dataclasses import replace

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader
from apps.fast9_case_source_join.services import join_case_source
from apps.intake_workflow.guards import require_synthetic_write, synthetic_atomic
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.normalization import normalize_title
from tools.fast9_case_source_join.__main__ import fixture_request
from tools.fast9_case_source_join.fixtures import synthetic_fixture
from tools.fast9_case_source_join.postgresql import TEST_DATABASE, TRUSTED_RUNNER, require_target

# Refuse unintended discovery before any test database creation/migration.
require_target(os.environ)
if (
    settings.TEST_RUNNER != TRUSTED_RUNNER
    or connection.vendor != "postgresql"
    or connection.settings_dict["TEST"]["NAME"] != TEST_DATABASE
):
    raise RuntimeError("trusted_exact_synthetic_runner_required")


class PostgreSQLJoinTests(TransactionTestCase):
    def setUp(self):
        if connection.settings_dict["NAME"] != TEST_DATABASE:
            raise RuntimeError("synthetic_test_identity_required")
        context = require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != TEST_DATABASE:
            raise RuntimeError("actual_synthetic_test_identity_mismatch")
        self.prepared, _ = synthetic_fixture()
        spec = self.prepared.spec
        # Fixed edition 7001 is part of the EXISTING case contract. Never remap
        # the case to an auto-generated edition or repair an occupied catalog.
        with synthetic_atomic(synthetic_fixtures_only=True):
            if ReferenceWork.objects.exists() or ReferenceEdition.objects.exists():
                raise RuntimeError("empty_synthetic_catalog_required")
            work = ReferenceWork.objects.create(
                pk=7001,
                source_namespace=spec.source_namespace,
                source_book_id=spec.source_book_id,
                title_original=spec.work_title,
                madhhab=spec.madhhab,
            )
            edition = ReferenceEdition.objects.create(
                pk=7001,
                work=work,
                edition_key=spec.edition_key,
                title=spec.edition_title,
                publisher=spec.publisher,
                source_archive_sha256=spec.source_archive_sha256,
                source_input_sha256=spec.source_input_sha256,
                input_name=spec.input_name,
                ingest_checksum=self.prepared.checksum,
                heading_count=3,
                root_count=1,
                max_depth=2,
            )
            for row in self.prepared.records:
                ReferenceHeading.objects.create(
                    pk=7000 + row.source_row_id,
                    edition=edition,
                    source_id=row.source_id,
                    source_row_id=row.source_row_id,
                    parent_id=7000 + row.parent_source_row_id if row.parent_source_row_id else None,
                    source_order=row.source_order,
                    position=row.position,
                    depth=row.depth,
                    source_page_id=row.source_page_id,
                    source_part=row.source_part,
                    source_page_number=row.source_page_number,
                    source_entry_number=row.source_entry_number,
                    title_original=row.title_original,
                    title_normalized=normalize_title(row.title_original),
                )

    def join(self, request, packet):
        return join_case_source(
            request,
            packet,
            prepared=self.prepared,
            reader=DjangoNavigationReader(),
            synthetic_fixtures_only=True,
        ).payload()

    def test_real_snapshot_join_is_exact_and_executes_no_writes(self):
        request, packet = fixture_request("intake-1")
        before = list(ReferenceHeading.objects.order_by("pk").values())
        with CaptureQueriesContext(connection) as queries:
            result = self.join(request, packet)
        self.assertEqual(result["status"], "VERIFIED_TECHNICAL")
        self.assertEqual(result["join"]["source_record"]["source_id"], "wave7-title-1")
        self.assertEqual(result["join"]["evidence"]["printed_page"], 7)
        self.assertEqual(result["owner_source"], "NOT_CONNECTED")
        sql = [q["sql"] for q in queries.captured_queries]
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY", sql)
        self.assertTrue(all(q.split()[0] in {"SELECT", "BEGIN", "SET", "COMMIT"} for q in sql))
        self.assertEqual(list(ReferenceHeading.objects.order_by("pk").values()), before)

    def test_cross_case_stale_row_and_edition_tampering_never_query_database(self):
        request, packet = fixture_request("intake-1")
        for altered in (
            replace(request, row_sha256="0" * 64),
            replace(request, edition_id=7002),
            replace(request, case_key="intake-4"),
        ):
            with CaptureQueriesContext(connection) as queries:
                result = self.join(altered, packet)
            self.assertEqual(result["status"], "REJECTED")
            self.assertIsNone(result["join"])
            self.assertEqual(len(queries), 0)
