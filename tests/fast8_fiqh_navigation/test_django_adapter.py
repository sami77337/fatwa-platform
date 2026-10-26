"""Offline ORM boundary tests; these do not claim PostgreSQL acceptance."""

import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import django

from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader
from apps.fast8_fiqh_navigation.services import CatalogNavigation
from apps.reference.records import prepare_catalog
from apps.reference_links.resolution import CatalogReadError, SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_fixture


class DjangoReaderBoundaryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()

    def setUp(self):
        self.prepared, self.headings = synthetic_fixture()
        self.navigation = CatalogNavigation(self.prepared, EDITION_ID)
        self.query = {"edition": str(EDITION_ID), "source_row_id": "40"}
        spec = self.prepared.spec
        self.edition = SimpleNamespace(
            pk=EDITION_ID,
            work=SimpleNamespace(
                source_namespace=spec.source_namespace,
                source_book_id=spec.source_book_id,
                title_original=spec.work_title,
                madhhab=spec.madhhab,
            ),
            edition_key=spec.edition_key,
            title=spec.edition_title,
            publisher=spec.publisher,
            source_archive_sha256=spec.source_archive_sha256,
            source_input_sha256=spec.source_input_sha256,
            input_name=spec.input_name,
            heading_count=spec.expected_rows,
            root_count=spec.expected_roots,
            max_depth=spec.expected_max_depth,
            ingest_checksum=self.prepared.checksum,
            ingested_at="2026-10-26T00:00:00.123456+00:00",
        )
        self.rows = []
        for record in self.prepared.records:
            row = asdict(record)
            parent = row.pop("parent_source_row_id")
            row.update(
                parent_id=parent + 1000 if parent is not None else None,
                parent__source_row_id=parent,
                parent__edition_id=EDITION_ID if parent is not None else None,
            )
            self.rows.append(row)
        self.connection = MagicMock(vendor="postgresql", in_atomic_block=False)
        self.connection.get_autocommit.return_value = True
        self.active = False
        self.events = []
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.execute.side_effect = lambda sql: self.events.append(sql)

        @contextmanager
        def atomic(**kwargs):
            self.assertEqual(kwargs, {"durable": True})
            self.active = True
            self.events.append("begin")
            try:
                yield
            finally:
                self.active = False
                self.events.append("end")

        self.atomic = self.enterContext(patch("django.db.transaction.atomic", side_effect=atomic))
        self.enterContext(patch("django.db.connection", self.connection))
        self.router = self.enterContext(
            patch("django.db.router.db_for_read", return_value="default")
        )

        def resolve(edition_id):
            self.assertTrue(self.active)
            self.assertEqual(edition_id, EDITION_ID)
            self.events.append("edition")
            return self.edition

        self.resolve = self.enterContext(
            patch("apps.reference.services.resolve_edition", side_effect=resolve)
        )
        self.manager = self.enterContext(patch("apps.reference.models.ReferenceHeading.objects"))
        self.values = self.manager.filter.return_value.order_by.return_value.values.return_value
        self.values.__getitem__.side_effect = lambda bound: deepcopy(self.rows[bound])
        self.evidence = SnapshotCatalog(self.headings)

        def evidence():
            self.assertTrue(self.active)
            return self.evidence

        self.catalog = self.enterContext(
            patch("apps.fast8_fiqh_navigation.django_adapter.DjangoCatalog", side_effect=evidence)
        )

    def navigate(self):
        return self.navigation.navigate(self.query, DjangoNavigationReader())

    def assert_closed(self, result):
        self.assertEqual(result.trail.status, "unverified")
        self.assertIsNone(result.edition_title)
        self.assertIsNone(result.publisher)
        self.assertIsNone(result.trail.current)
        self.assertIsNone(result.trail.previous)
        self.assertIsNone(result.trail.next)
        self.assertEqual(result.trail.breadcrumbs, ())
        self.assertIsNone(result.trail.catalog_return_url)
        self.assertIsNone(result.trail.research_return_url)

    def test_exact_topology_and_original_titles_inside_one_read_only_snapshot(self):
        before = deepcopy(vars(self.edition))
        result = self.navigate()
        self.assertEqual(result.trail.status, "verified")
        self.assertEqual(result.trail.current.evidence, self.headings[2])
        self.assertEqual(result.edition_title, self.prepared.spec.edition_title)
        self.assertEqual(result.publisher, self.prepared.spec.publisher)
        self.assertEqual(vars(self.edition), before)
        self.assertEqual(
            self.events,
            [
                "begin",
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
                "edition",
                "end",
            ],
        )
        self.assertFalse(self.active)
        self.manager.filter.assert_called_once_with(edition_id=EDITION_ID)
        self.values.__getitem__.assert_called_once_with(slice(None, len(self.rows) + 1))
        self.cursor.execute.assert_called_once()
        for operation in ("create", "bulk_create", "update", "delete", "get_or_create"):
            getattr(self.manager, operation).assert_not_called()

    def test_evidence_is_consumed_before_snapshot_exit(self):
        base = self.evidence

        class Evidence:
            def lookup(inner, edition, row):
                self.assertTrue(self.active)
                self.assertEqual(self.events[-1], "edition")
                return base.lookup(edition, row)

        self.evidence = Evidence()
        self.assertEqual(self.navigate().trail.status, "verified")

    def test_invalid_edition_never_opens_transaction(self):
        for edition in (None, True, 1.0, "7001", 0, -1, 2**63):
            with self.subTest(edition=edition), self.assertRaises(CatalogReadError):
                with DjangoNavigationReader().snapshot(edition):
                    self.fail("invalid identity yielded")
        self.atomic.assert_not_called()
        self.resolve.assert_not_called()
        self.connection.cursor.assert_not_called()

    def test_non_postgresql_and_nondefault_router_close_without_read(self):
        self.connection.vendor = "sqlite"
        self.assert_closed(self.navigate())
        self.connection.vendor = "postgresql"
        for routed_model in (0, 1, 2):
            self.router.side_effect = [
                "replica" if i == routed_model else "default" for i in range(3)
            ]
            self.assert_closed(self.navigate())
        self.atomic.assert_not_called()
        self.resolve.assert_not_called()

    def test_nested_atomic_or_manual_transaction_never_changes_isolation(self):
        self.connection.in_atomic_block = True
        self.assert_closed(self.navigate())
        self.connection.in_atomic_block = False
        self.connection.get_autocommit.return_value = False
        self.assert_closed(self.navigate())
        self.atomic.assert_not_called()
        self.connection.cursor.assert_not_called()
        self.resolve.assert_not_called()

    def test_cross_edition_parent_with_same_source_row_is_rejected(self):
        self.rows[1]["parent__edition_id"] = EDITION_ID + 1
        self.assert_closed(self.navigate())
        self.catalog.assert_not_called()

    def test_missing_joined_parent_is_rejected(self):
        for key in ("parent__edition_id", "parent__source_row_id"):
            with self.subTest(key=key):
                original = self.rows[1][key]
                self.rows[1][key] = None
                self.assert_closed(self.navigate())
                self.rows[1][key] = original
        self.catalog.assert_not_called()

    def test_extra_or_missing_unrelated_tail_is_not_silently_ignored(self):
        original = deepcopy(self.rows)
        for rows in (original[:-1], original + [deepcopy(original[-1])]):
            with self.subTest(count=len(rows)):
                self.rows = rows
                self.assert_closed(self.navigate())
        self.catalog.assert_not_called()

    def test_declared_count_is_bounded_before_querying_headings(self):
        for count in (0, 20001):
            with self.subTest(count=count):
                self.edition.heading_count = count
                self.assert_closed(self.navigate())
        self.manager.filter.assert_not_called()

    def test_each_original_row_field_is_covered_by_stored_checksum(self):
        changes = {
            "source_id": "synthetic-different",
            "source_row_id": 99,
            "source_order": 99,
            "position": 99,
            "depth": 3,
            "source_page_id": 999,
            "source_part": "جزء اصطناعي مختلف",
            "source_page_number": 99,
            "source_entry_number": 1,
            "title_original": "خاتمة مختلفة اصطناعية",
        }
        original = deepcopy(self.rows[-1])
        for key, value in changes.items():
            with self.subTest(field=key):
                self.rows[-1] = {**original, key: value}
                self.assert_closed(self.navigate())
        self.catalog.assert_not_called()

    def test_every_work_and_edition_metadata_field_is_checked(self):
        for target, key, value in (
            (self.edition.work, "source_namespace", "other-synthetic"),
            (self.edition.work, "source_book_id", "other"),
            (self.edition.work, "title_original", "مرجع اصطناعي آخر"),
            (self.edition.work, "madhhab", "آخر اصطناعي"),
            (self.edition, "edition_key", "other-synthetic"),
            (self.edition, "title", "طبعة اصطناعية أخرى"),
            (self.edition, "publisher", "ناشر اصطناعي آخر"),
            (self.edition, "source_archive_sha256", "c" * 64),
            (self.edition, "source_input_sha256", "c" * 64),
            (self.edition, "input_name", "other-synthetic.json"),
            (self.edition, "root_count", 1),
            (self.edition, "max_depth", 4),
            (self.edition, "ingest_checksum", "c" * 64),
        ):
            with self.subTest(field=key):
                original = getattr(target, key)
                setattr(target, key, value)
                self.assert_closed(self.navigate())
                setattr(target, key, original)
        self.catalog.assert_not_called()

    def test_self_consistent_catalog_still_must_match_independent_expected_contract(self):
        changed = prepare_catalog(
            replace(self.prepared.spec, edition_title="طبعة اصطناعية أخرى"),
            self.prepared.records,
        )
        self.edition.title = changed.spec.edition_title
        self.edition.ingest_checksum = changed.checksum
        self.assert_closed(self.navigate())
        self.catalog.assert_called_once()

    def test_valid_topology_does_not_override_conflicting_heading_evidence(self):
        changed = replace(self.headings[2], printed_page=999)
        self.evidence = SnapshotCatalog(self.headings[:2] + (changed,) + self.headings[3:])
        self.assert_closed(self.navigate())

    def test_database_errors_are_closed_and_do_not_disclose_details(self):
        from django.db import DatabaseError

        from apps.reference.services import EditionNotFound

        for error in (DatabaseError("SYNTHETIC_PRIVATE_CONNECTION"), EditionNotFound("missing")):
            with self.subTest(error=type(error).__name__):
                self.resolve.side_effect = error
                result = self.navigate()
                self.assert_closed(result)
                self.assertEqual(result.trail.reason, "catalog_unavailable")
                self.assertNotIn("SYNTHETIC_PRIVATE_CONNECTION", str(asdict(result)))
                self.assertFalse(self.active)

    def test_connection_failure_before_atomic_is_closed(self):
        from django.db import DatabaseError

        self.connection.get_autocommit.side_effect = DatabaseError("SYNTHETIC_PRIVATE_CONNECTION")
        result = self.navigate()
        self.assert_closed(result)
        self.assertNotIn("SYNTHETIC_PRIVATE_CONNECTION", str(asdict(result)))
        self.atomic.assert_not_called()

    def test_database_error_on_transaction_exit_cannot_return_verified_data(self):
        from django.db import DatabaseError

        @contextmanager
        def failed_commit(**kwargs):
            self.active = True
            try:
                yield
                raise DatabaseError("SYNTHETIC_PRIVATE_CONNECTION")
            finally:
                self.active = False

        self.atomic.side_effect = failed_commit
        result = self.navigate()
        self.assert_closed(result)
        self.assertEqual(result.trail.reason, "catalog_unavailable")
        self.assertNotIn("SYNTHETIC_PRIVATE_CONNECTION", str(asdict(result)))
