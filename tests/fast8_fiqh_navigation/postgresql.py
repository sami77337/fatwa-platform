"""Explicit PostgreSQL acceptance on the designated synthetic test database only.

Set PGTESTDATABASE=test_fast8_fiqh_navigation_synthetic, then run:
python -B manage.py test tests.fast8_fiqh_navigation.postgresql
    --settings=config.settings.test --noinput --verbosity=2

This module is intentionally outside test_*.py offline discovery. Missing or
incorrect PostgreSQL is an error, never a skip or a synthetic acceptance claim.
"""

from django.db import connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader
from apps.fast8_fiqh_navigation.services import CatalogNavigation
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference_links.resolution import CatalogReadError
from tools.fiqh_reading_trail.fixtures import synthetic_fixture

TEST_DATABASE = "test_fast8_fiqh_navigation_synthetic"

# DiscoverRunner imports this module before setup_databases. Refuse the wrong
# target before test database creation/migrations, not merely before fixtures.
if connection.vendor != "postgresql" or connection.settings_dict["TEST"]["NAME"] != TEST_DATABASE:
    raise RuntimeError("Dedicated synthetic PostgreSQL test database required")


class PostgreSQLNavigationTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # Reject accidental execution under unittest or against a development
        # catalog before any fixture write. Django's runner creates the test DB.
        if connection.vendor != "postgresql" or connection.settings_dict["NAME"] != TEST_DATABASE:
            raise RuntimeError("Dedicated synthetic PostgreSQL test database required")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone() != (TEST_DATABASE,):
                raise RuntimeError("PostgreSQL test database identity mismatch")
        super().setUpClass()

    def setUp(self):
        self.prepared, self.expected_headings = synthetic_fixture()
        if ReferenceWork.objects.exists():
            raise RuntimeError("Synthetic navigation fixture requires an empty catalog")
        outcome = ingest_catalog(
            self.prepared.spec,
            self.prepared.records,
            dry_run=False,
            expected_checksum=self.prepared.checksum,
        )
        self.edition_id = outcome.edition_id
        self.navigation = CatalogNavigation(self.prepared, self.edition_id)
        self.reader = DjangoNavigationReader()
        self.query = {"edition": str(self.edition_id), "source_row_id": "40"}

    def test_actual_navigation_preserves_original_source_metadata_without_writes(self):
        before = list(ReferenceEdition.objects.values())
        heading_before = list(ReferenceHeading.objects.order_by("pk").values())
        with CaptureQueriesContext(connection) as captured:
            result = self.navigation.navigate(self.query, self.reader)
        self.assertEqual(result.trail.status, "verified")
        self.assertEqual(
            result.trail.current.evidence.heading_title, self.expected_headings[2].heading_title
        )
        self.assertEqual(result.trail.current.evidence.printed_part, "تمهيد")
        self.assertEqual(result.trail.current.evidence.printed_page, 3)
        self.assertEqual(result.trail.current.evidence.edition_id, self.edition_id)
        self.assertEqual(result.edition_title, self.prepared.spec.edition_title)
        self.assertEqual(result.publisher, self.prepared.spec.publisher)
        self.assertEqual(
            [item.evidence.source_row_id for item in result.trail.breadcrumbs], [1, 2, 40]
        )
        self.assertEqual(result.trail.previous.evidence.source_row_id, 2)
        self.assertEqual(result.trail.next.evidence.source_row_id, 41)
        self.assertEqual(list(ReferenceEdition.objects.values()), before)
        self.assertEqual(list(ReferenceHeading.objects.order_by("pk").values()), heading_before)
        sql = [query["sql"] for query in captured.captured_queries]
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY", sql)
        self.assertTrue(sql)
        self.assertTrue(
            all(query.split(None, 1)[0] in {"SELECT", "BEGIN", "COMMIT", "SET"} for query in sql)
        )

    def test_postgresql_confirms_snapshot_mode_and_refuses_an_attempted_write(self):
        with self.reader.snapshot(self.edition_id):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                self.assertEqual(cursor.fetchone(), ("repeatable read",))
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone(), ("on",))
        # This deliberately attempted update is confined to the synthetic test
        # DB and must be rejected by PostgreSQL's read-only transaction itself.
        before = list(ReferenceWork.objects.values())
        with self.assertRaises(CatalogReadError) as raised:
            with self.reader.snapshot(self.edition_id):
                ReferenceWork.objects.update(madhhab="اصطناعي مرفوض")
        database_error = raised.exception.__cause__
        self.assertEqual(database_error.__cause__.sqlstate, "25006")
        self.assertEqual(list(ReferenceWork.objects.values()), before)
        self.assertTrue(connection.get_autocommit())

    def test_outer_transaction_and_unknown_edition_cannot_supply_navigation(self):
        with transaction.atomic():
            result = self.navigation.navigate(self.query, self.reader)
            self.assertEqual(result.trail.status, "unverified")
            self.assertIsNone(result.trail.current)
            self.assertIsNone(result.edition_title)
        missing = self.edition_id + 1000000
        navigation = CatalogNavigation(self.prepared, missing)
        result = navigation.navigate({"edition": str(missing), "source_row_id": "40"}, self.reader)
        self.assertEqual(result.trail.status, "unverified")
        self.assertIsNone(result.trail.current)
        self.assertIsNone(result.edition_title)
