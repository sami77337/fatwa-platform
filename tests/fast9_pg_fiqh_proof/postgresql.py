"""Explicit guarded real-PG acceptance; never collected by test_*.py discovery."""

from tools.fast9_pg_fiqh_proof import runner

# Before model imports, suite discovery, database creation, or migrations.
runner.require_discovery()

from dataclasses import asdict, replace  # noqa: E402

from django.db import IntegrityError, connection, transaction  # noqa: E402
from django.test import TransactionTestCase  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader  # noqa: E402
from apps.fast8_fiqh_navigation.services import CatalogNavigation  # noqa: E402
from apps.reference.ingest import ingest_catalog  # noqa: E402
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork  # noqa: E402
from apps.reference.records import prepare_catalog  # noqa: E402
from apps.reference_links.resolution import CatalogReadError  # noqa: E402
from tools.fast9_pg_fiqh_proof.proof import CHECKSUM, checked_fixture, emit  # noqa: E402


class PostgreSQLSourceTrailTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        runner.require_running_database()
        super().setUpClass()

    def setUp(self):
        # This runs before every fixture write, not just once per process.
        runner.require_running_database()
        self.prepared, self.expected = checked_fixture()
        if any(
            model.objects.exists()
            for model in (
                ReferenceWork,
                ReferenceEdition,
                ReferenceHeading,
            )
        ):
            raise runner.SyntheticGuardError("Synthetic fixture requires an empty catalog")
        outcome = ingest_catalog(
            self.prepared.spec,
            self.prepared.records,
            dry_run=False,
            expected_checksum=CHECKSUM,
        )
        self.edition_id = outcome.edition_id
        self.reader = DjangoNavigationReader()
        self.navigation = CatalogNavigation(self.prepared, self.edition_id)

    def state(self):
        # Includes PKs, every original field, normalized fields, and ingested_at.
        return [
            list(model.objects.order_by("pk").values())
            for model in (
                ReferenceWork,
                ReferenceEdition,
                ReferenceHeading,
            )
        ]

    def navigate(self, row=40, reader=None):
        return self.navigation.navigate(
            {"edition": str(self.edition_id), "source_row_id": str(row)},
            reader or self.reader,
        )

    def assert_closed(self, result):
        self.assertEqual(result.trail.status, "unverified")
        self.assertIsNone(result.trail.current)
        self.assertEqual(result.trail.breadcrumbs, ())
        self.assertIsNone(result.trail.previous)
        self.assertIsNone(result.trail.next)
        self.assertIsNone(result.edition_title)
        self.assertIsNone(result.publisher)

    def test_exact_catalog_topology_original_unicode_and_source_trail(self):
        before = self.state()
        order = [1, 2, 40, 41, 42, 3, 8, 9, 10]
        self.assertEqual([row.source_row_id for row in self.prepared.records], order)
        with self.reader.snapshot(self.edition_id) as snapshot:
            self.assertEqual(snapshot.prepared, self.prepared)
            self.assertEqual(snapshot.prepared.checksum, CHECKSUM)
        with CaptureQueriesContext(connection) as captured:
            for index, (record, expected) in enumerate(
                zip(
                    self.prepared.records,
                    self.expected,
                    strict=True,
                )
            ):
                result = self.navigate(record.source_row_id)
                self.assertEqual(result.trail.status, "verified")
                item = result.trail.current
                self.assertEqual(item.evidence, replace(expected, edition_id=self.edition_id))
                self.assertEqual(
                    item.evidence.heading_title.encode("utf-8"),
                    record.title_original.encode("utf-8"),
                )
                for field in (
                    "source_id",
                    "parent_source_row_id",
                    "source_order",
                    "position",
                    "depth",
                ):
                    self.assertEqual(getattr(item, field), getattr(record, field))
                previous, following = result.trail.previous, result.trail.next
                self.assertEqual(
                    previous.evidence.source_row_id if previous else None,
                    order[index - 1] if index else None,
                )
                self.assertEqual(
                    following.evidence.source_row_id if following else None,
                    order[index + 1] if index + 1 < len(order) else None,
                )
                self.assertEqual(
                    tuple(x.evidence.heading_title for x in result.trail.breadcrumbs), expected.path
                )
                self.assertEqual(result.edition_title, self.prepared.spec.edition_title)
                self.assertEqual(result.publisher, self.prepared.spec.publisher)
        sql = [query["sql"] for query in captured.captured_queries]
        self.assertEqual(sql.count("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"), 9)
        self.assertTrue(
            all(query.split(None, 1)[0] in {"SELECT", "BEGIN", "COMMIT", "SET"} for query in sql)
        )
        self.assertEqual(self.state(), before)
        emit(
            "exact_source_trail",
            rows=9,
            roots=2,
            max_depth=5,
            checksum=CHECKSUM,
            all_catalog_fields_unchanged=True,
        )

    def test_transaction_evidence_and_insert_update_delete_are_rejected(self):
        before = self.state()
        with self.reader.snapshot(self.edition_id):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                self.assertEqual(cursor.fetchone(), ("repeatable read",))
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone(), ("on",))
                identity = runner.verify_identity(cursor, runner.TEST_DATABASE)
        for verb, sql in (
            (
                "INSERT",
                "INSERT INTO reference_referencework "
                "(source_namespace, source_book_id, title_original, madhhab) "
                "VALUES ('fast9-synthetic', 'mutation', 'synthetic', 'synthetic')",
            ),
            ("UPDATE", "UPDATE reference_referencework SET madhhab = 'synthetic-mutation'"),
            ("DELETE", "DELETE FROM reference_referenceheading WHERE source_row_id = 42"),
        ):
            with self.subTest(verb=verb):
                with self.assertRaises(CatalogReadError) as caught:
                    with self.reader.snapshot(self.edition_id):
                        with connection.cursor() as cursor:
                            cursor.execute(sql)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, "25006")
                self.assertTrue(connection.get_autocommit())
                self.assertEqual(self.state(), before)
        emit(
            "transaction",
            **identity,
            isolation="repeatable read",
            read_only="on",
            rejected_verbs=["INSERT", "UPDATE", "DELETE"],
            sqlstate="25006",
        )

    def fixture_contract(self, key):
        return prepare_catalog(replace(self.prepared.spec, edition_key=key), self.prepared.records)

    def insert_edition(self, pin, *, edition_fields=None, heading_fields=None, omit=None):
        """Seed an independent inconsistent snapshot with ordinary first INSERTs."""
        runner.require_running_database()
        fields = ReferenceEdition.objects.values().get(pk=self.edition_id)
        del fields["id"], fields["ingested_at"]
        fields.update(edition_key=pin.spec.edition_key, ingest_checksum=pin.checksum)
        edition = ReferenceEdition.objects.create(**(fields | (edition_fields or {})))
        new_pks = {}
        originals = ReferenceHeading.objects.filter(edition_id=self.edition_id).order_by(
            "source_order"
        )
        for row in originals.values():
            source_row = row["source_row_id"]
            if source_row == omit:
                continue
            old_pk = row.pop("id")
            row.update(edition_id=edition.pk, parent_id=new_pks.get(row["parent_id"]))
            row.update((heading_fields or {}).get(source_row, {}))
            new_pks[old_pk] = ReferenceHeading.objects.create(**row).pk
        return edition.pk

    def assert_pin_rejects(self, pin, edition):
        before = self.state()
        result = CatalogNavigation(pin, edition).navigate(
            {"edition": str(edition), "source_row_id": "40"}, self.reader
        )
        self.assert_closed(result)
        self.assertEqual(before, self.state())
        return result

    def test_stale_checksum_refuses_mutated_original_fields(self):
        row = ReferenceHeading.objects.get(edition_id=self.edition_id, source_row_id=40)
        for field, value in (
            ("title_original", row.title_original.strip()),
            ("source_part", "مقدمة اصطناعية"),
            ("source_page_number", 4),
            ("source_page_id", 999),
            ("source_id", "synthetic-altered"),
            ("source_order", 31),
            ("position", 6),
            ("source_entry_number", 99),
        ):
            with self.subTest(field=field):
                pin = self.fixture_contract("stale-" + field)
                edition = self.insert_edition(pin, heading_fields={40: {field: value}})
                self.assert_pin_rejects(pin, edition)

    def test_recomputed_checksum_cannot_replace_independent_source_contract(self):
        pin = self.fixture_contract("recomputed")
        changed = prepare_catalog(
            pin.spec,
            tuple(
                replace(r, source_page_number=4) if r.source_row_id == 40 else r
                for r in pin.records
            ),
        )
        edition = self.insert_edition(
            pin,
            edition_fields={"ingest_checksum": changed.checksum},
            heading_fields={40: {"source_page_number": 4}},
        )
        with self.reader.snapshot(edition) as snapshot:
            self.assertEqual(snapshot.prepared, changed)
        result = self.assert_pin_rejects(pin, edition)
        self.assertEqual(result.trail.reason, "catalog_evidence_mismatch")

    def test_topology_drift_missing_row_and_foreign_parent_fail_closed(self):
        missing = self.fixture_contract("missing-leaf")
        edition = self.insert_edition(missing, omit=42)
        self.assert_pin_rejects(missing, edition)
        before = self.state()
        target = ReferenceHeading.objects.filter(edition_id=self.edition_id, source_row_id=42)
        with self.assertRaises(IntegrityError) as caught:
            target.delete()
        self.assertEqual(caught.exception.__cause__.sqlstate, "23514")
        self.assertEqual(before, self.state())

        # Only an INSERT can exercise the parent trigger with the schema's
        # update/delete protection intact. This parent has the correct depth.
        foreign = ReferenceHeading.objects.get(edition_id=self.edition_id, source_row_id=2)
        with self.assertRaises(IntegrityError) as caught:
            self.insert_edition(
                self.fixture_contract("foreign-parent"),
                heading_fields={40: {"parent_id": foreign.pk}},
            )
        self.assertEqual(caught.exception.__cause__.sqlstate, "23514")
        self.assertIn("Parent must exist in the same edition", str(caught.exception))
        # A depth-correct but wrong parent within an edition is structurally
        # allowed. Recompute the stored checksum so only the independent pin
        # can reject the alternate hierarchy.
        pin = self.fixture_contract("alternate-parent")
        changed = prepare_catalog(
            pin.spec,
            tuple(
                replace(r, parent_source_row_id=8) if r.source_row_id == 2 else r
                for r in pin.records
            ),
        )
        edition = ingest_catalog(
            changed.spec, changed.records, dry_run=False, expected_checksum=changed.checksum
        ).edition_id
        self.assert_pin_rejects(pin, edition)

    def test_source_identity_metadata_and_checksum_drift_fail_closed(self):
        original = ReferenceEdition.objects.filter(pk=self.edition_id)
        before = self.state()
        with self.assertRaises(IntegrityError) as caught:
            original.update(publisher="آخر")
        self.assertEqual(caught.exception.__cause__.sqlstate, "23514")
        self.assertEqual(before, self.state())
        for field, value in (
            ("source_archive_sha256", "c" * 64),
            ("source_input_sha256", "d" * 64),
            ("ingest_checksum", "0" * 64),
            ("edition_key", "altered-synthetic"),
            ("title", "طبعة مغايرة اصطناعية"),
            ("publisher", "ناشر مغاير اصطناعي"),
            ("input_name", "other-synthetic.json"),
            ("heading_count", 10),
            ("root_count", 3),
            ("max_depth", 4),
        ):
            with self.subTest(field=field):
                pin = self.fixture_contract("metadata-" + field)
                edition = self.insert_edition(pin, edition_fields={field: value})
                self.assert_pin_rejects(pin, edition)

    def test_unknown_unjoined_and_nested_transactions_never_supply_evidence(self):
        before = self.state()
        query = {"edition": str(self.edition_id), "source_row_id": "40"}
        disconnected = self.navigation.navigate(query)
        self.assert_closed(disconnected)
        self.assertEqual(disconnected.trail.reason, "NOT_CONNECTED")
        self.assert_closed(self.navigate(999999))
        missing = self.edition_id + 1000000
        self.assert_closed(
            CatalogNavigation(self.prepared, missing).navigate(
                {"edition": str(missing), "source_row_id": "40"},
                self.reader,
            )
        )
        with transaction.atomic():
            self.assert_closed(self.navigate())
        self.assertEqual(self.state(), before)

    def test_repeatable_read_snapshot_stays_stable_across_committed_synthetic_change(self):
        # A second connection changes only the freshly created synthetic catalog.
        writer = connection.copy(alias="fast9_synthetic_writer")
        try:
            with writer.cursor() as cursor:
                runner.verify_identity(cursor, runner.TEST_DATABASE)
            extra = ReferenceHeading.objects.filter(
                edition_id=self.edition_id, source_id="fast9-committed-extra"
            )
            self.assertFalse(extra.exists())
            with self.reader.snapshot(self.edition_id) as snapshot:
                with writer.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO reference_referenceheading "
                        "(edition_id, source_id, source_row_id, parent_id, source_order, position,"
                        " depth, source_page_id, source_part, source_page_number, title_original,"
                        " title_normalized) SELECT edition_id,'fast9-committed-extra',999,parent_id,"
                        "999,999,depth,source_page_id,source_part,source_page_number,title_original,"
                        "title_normalized FROM reference_referenceheading WHERE edition_id=%s "
                        "AND source_row_id=40",
                        [self.edition_id],
                    )
                    self.assertEqual(cursor.rowcount, 1)
                self.assertFalse(extra.exists())
                from apps.fiqh_reading_trail.services import ReadingTrail

                result = ReadingTrail(self.prepared, self.edition_id).navigate(
                    40, snapshot.evidence
                )
                self.assertEqual(result.status, "verified")
                self.assertEqual(
                    result.current.evidence.heading_title, self.prepared.records[2].title_original
                )
                self.assertEqual(asdict(snapshot.prepared), asdict(self.prepared))
            self.assertTrue(extra.exists())
            self.assert_closed(self.navigate())
            emit(
                "snapshot_stability",
                concurrent_commit_visible_inside=False,
                subsequent_snapshot="unverified_after_committed_insert",
            )
        finally:
            writer.close()
