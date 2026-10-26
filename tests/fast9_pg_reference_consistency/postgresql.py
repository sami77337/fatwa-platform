"""Actual synthetic PostgreSQL tests; deliberately excluded from offline discovery.

Only tools.fast9_pg_reference_consistency may launch the existing trusted runner.
"""

import os
from dataclasses import replace

from tools.fast9_pg_reference_consistency.guard import (
    TEST_DATABASE,
    require_target,
    validate_environment,
)

# DiscoverRunner builds the suite BEFORE setup_databases/migrations. Fail early.
validate_environment(os.environ)

from django.db import connection, transaction  # noqa: E402
from django.test import TransactionTestCase  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from apps.fast9_pg_reference_consistency.django_adapter import DjangoConsistencyReader  # noqa: E402
from apps.fast9_pg_reference_consistency.services import check_catalog  # noqa: E402
from apps.reference.ingest import ingest_catalog  # noqa: E402
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork  # noqa: E402
from apps.reference.records import prepare_catalog  # noqa: E402
from tools.fast9_pg_reference_consistency.fixtures import synthetic_fixture  # noqa: E402

if connection.vendor != "postgresql" or connection.settings_dict["TEST"]["NAME"] != TEST_DATABASE:
    raise RuntimeError("Exact synthetic test database required before test setup")


class PostgreSQLConsistencyTests(TransactionTestCase):
    available_apps = ["apps.reference"]

    @classmethod
    def setUpClass(cls):
        require_target(test_database=True)
        super().setUpClass()

    def setUp(self):
        require_target(test_database=True)
        if ReferenceWork.objects.exists():
            raise RuntimeError("Empty synthetic reference catalog required")
        self.pin = synthetic_fixture()
        result = ingest_catalog(
            self.pin.spec, self.pin.records, dry_run=False, expected_checksum=self.pin.checksum
        )
        self.edition_id = result.edition_id
        self.reader = DjangoConsistencyReader(using="default")

    def check(self):
        return check_catalog(self.pin, self.edition_id, self.reader)

    def test_actual_ingest_then_read_only_consistency_preserves_all_rows_and_timestamps(self):
        before = [
            list(model.objects.order_by("pk").values())
            for model in (ReferenceWork, ReferenceEdition, ReferenceHeading)
        ]
        with CaptureQueriesContext(connection) as captured:
            result = self.check()
        self.assertEqual(result.status, "CONSISTENT")
        self.assertEqual(result.checked_rows, 4)
        self.assertEqual(result.source_acceptance, "NOT_CONNECTED")
        sql = [query["sql"] for query in captured.captured_queries]
        self.assertEqual(sum(query.startswith("SELECT") for query in sql), 3)
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY", sql)
        self.assertTrue(
            all(query.split(None, 1)[0] in {"BEGIN", "SELECT", "SET", "COMMIT"} for query in sql)
        )
        after = [
            list(model.objects.order_by("pk").values())
            for model in (ReferenceWork, ReferenceEdition, ReferenceHeading)
        ]
        self.assertEqual(after, before)
        # Real domain connection: existing navigation and reference evidence still agree.
        from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader
        from apps.fast8_fiqh_navigation.services import CatalogNavigation

        navigation = CatalogNavigation(self.pin, self.edition_id).navigate(
            {"edition": str(self.edition_id), "source_row_id": "30"},
            DjangoNavigationReader(),
        )
        self.assertEqual(navigation.trail.status, "verified")
        self.assertEqual(navigation.trail.current.evidence.printed_part, "الأول")
        self.assertEqual(navigation.trail.current.evidence.printed_page, 3)

    def test_changed_heading_fields_including_normalized_title_are_rejected(self):
        row = ReferenceHeading.objects.get(edition_id=self.edition_id, source_row_id=30)
        for field, changed in (
            ("title_original", "عنوان اصطناعي متغير"),
            ("title_normalized", "corrupt"),
            ("source_part", "جزء مختلف"),
            ("source_page_number", 999),
            ("source_order", 16),
            ("position", 4),
            ("source_page_id", 999),
            ("source_entry_number", None),
            ("source_id", "changed-synthetic"),
        ):
            with self.subTest(field=field):
                ReferenceHeading.objects.filter(pk=row.pk).update(**{field: changed})
                self.assertEqual(self.check().status, "INCONSISTENT")
                ReferenceHeading.objects.filter(pk=row.pk).update(**{field: getattr(row, field)})

    def test_metadata_and_checksum_changes_are_rejected(self):
        edition = ReferenceEdition.objects.get(pk=self.edition_id)
        for field, changed in (
            ("ingest_checksum", "0" * 64),
            ("heading_count", 5),
            ("source_input_sha256", "0" * 64),
            ("title", "طبعة بديلة"),
        ):
            with self.subTest(field=field):
                ReferenceEdition.objects.filter(pk=self.edition_id).update(**{field: changed})
                self.assertEqual(self.check().status, "INCONSISTENT")
                ReferenceEdition.objects.filter(pk=self.edition_id).update(
                    **{field: getattr(edition, field)}
                )
        ReferenceWork.objects.update(title_original="مرجع اصطناعي متغير")
        self.assertEqual(self.check().status, "INCONSISTENT")

    def test_extra_and_absent_rows_rejected(self):
        row = ReferenceHeading.objects.get(edition_id=self.edition_id, source_row_id=50)
        original_pk = row.pk
        row.pk = None
        row.source_id = "synthetic-extra"
        row.source_row_id = 999
        row.source_order = 999
        row.position = 999
        row.save(force_insert=True)
        self.assertEqual(self.check().reason, "heading_count")
        row.delete()
        ReferenceHeading.objects.filter(pk=original_pk).delete()
        self.assertEqual(self.check().reason, "heading_count")

    def test_cross_edition_parent_same_source_row_id_and_wrong_edition_rejected(self):
        other = prepare_catalog(
            replace(self.pin.spec, edition_key="synthetic-other"), self.pin.records
        )
        other_id = ingest_catalog(
            other.spec, other.records, dry_run=False, expected_checksum=other.checksum
        ).edition_id
        # A separate valid edition is outside the pinned scope, not an extra heading.
        self.assertEqual(self.check().status, "CONSISTENT")
        parent = ReferenceHeading.objects.get(edition_id=other_id, source_row_id=10)
        ReferenceHeading.objects.filter(edition_id=self.edition_id, source_row_id=30).update(
            parent=parent
        )
        self.assertEqual(self.check().status, "INCONSISTENT")
        self.assertEqual(check_catalog(self.pin, other_id, self.reader).status, "NOT_CONNECTED")

    def test_nested_transaction_and_unknown_edition_never_claim_consistency(self):
        with transaction.atomic():
            self.assertEqual(self.check().status, "NOT_CONNECTED")
        self.assertEqual(
            check_catalog(self.pin, self.edition_id + 99999, self.reader).status, "NOT_CONNECTED"
        )

    def test_server_enforces_snapshot_mode_and_rejects_injected_write(self):
        before = list(ReferenceWork.objects.values())
        observations = []

        def observe(execute, sql, params, many, context):
            if sql.startswith("SELECT") and not observations:
                # Use the underlying cursor to avoid recursively invoking this observer.
                cursor = context["cursor"].cursor
                cursor.execute("SHOW transaction_isolation")
                isolation = cursor.fetchone()[0]
                cursor.execute("SHOW transaction_read_only")
                observations.append((isolation, cursor.fetchone()[0]))
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            self.assertEqual(self.check().status, "CONSISTENT")
        self.assertEqual(observations, [("repeatable read", "on")])

        errors = []

        def inject(execute, sql, params, many, context):
            if sql.startswith("SELECT"):
                try:
                    execute(
                        "UPDATE reference_referencework SET madhhab = madhhab", None, False, context
                    )
                except Exception as error:
                    errors.append(error.__cause__.sqlstate)
                    raise
            return execute(sql, params, many, context)

        with connection.execute_wrapper(inject):
            self.assertEqual(self.check().status, "NOT_CONNECTED")
        self.assertEqual(errors, ["25006"])
        self.assertEqual(list(ReferenceWork.objects.values()), before)
