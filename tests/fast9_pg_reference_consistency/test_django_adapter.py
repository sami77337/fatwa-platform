"""Offline ORM boundary assertions; no PostgreSQL or SQLite fallback."""

import os
from contextlib import contextmanager
from copy import deepcopy
from unittest import TestCase
from unittest.mock import MagicMock, patch

import django

from apps.fast9_pg_reference_consistency.django_adapter import DjangoConsistencyReader
from apps.fast9_pg_reference_consistency.services import check_catalog
from tools.fast9_pg_reference_consistency.fixtures import synthetic_fixture

from .support import EDITION_ID, snapshot


class ORMReadTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()

    def setUp(self):
        self.pin = synthetic_fixture()
        self.rows = snapshot()
        self.reader = DjangoConsistencyReader(using="synthetic")
        self.connection = MagicMock(vendor="postgresql", in_atomic_block=False)
        self.connection.get_autocommit.return_value = True
        self.enterContext(patch("django.db.connections", {"synthetic": self.connection}))
        self.events = []
        self.active = False
        cursor = self.connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = lambda sql: self.events.append(sql)

        @contextmanager
        def atomic(**kwargs):
            self.assertEqual(kwargs, {"using": "synthetic", "durable": True})
            self.active = True
            self.events.append("BEGIN")
            try:
                yield
            finally:
                self.active = False
                self.events.append("EXIT")

        self.atomic = self.enterContext(patch("django.db.transaction.atomic", side_effect=atomic))
        self.managers = []
        self.values = []
        for model, part in (
            ("ReferenceWork", "works"),
            ("ReferenceEdition", "editions"),
            ("ReferenceHeading", "headings"),
        ):
            manager = self.enterContext(patch("apps.reference.models." + model + ".objects"))
            values = manager.using.return_value.filter.return_value.order_by.return_value.values

            def bounded(bound, part=part):
                self.assertTrue(self.active)
                self.events.append(part)
                return deepcopy(getattr(self.rows, part)[bound])

            values.return_value.__getitem__.side_effect = bounded
            self.managers.append(manager)
            self.values.append(values)

    def check(self):
        return check_catalog(self.pin, EDITION_ID, self.reader)

    def test_reads_explicit_alias_bounded_rows_in_one_read_only_snapshot(self):
        result = self.check()
        self.assertEqual(result.status, "CONSISTENT")
        self.assertFalse(self.active)
        self.assertEqual(
            self.events,
            [
                "BEGIN",
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
                "SET LOCAL statement_timeout = '3000ms'",
                "SET LOCAL lock_timeout = '1000ms'",
                "works",
                "editions",
                "headings",
                "EXIT",
            ],
        )
        for manager, values, limit in zip(self.managers, self.values, (2, 2, 5), strict=True):
            manager.using.assert_called_once_with("synthetic")
            values.return_value.__getitem__.assert_called_once_with(slice(None, limit))
            for operation in ("create", "update", "delete", "bulk_create", "get_or_create"):
                getattr(manager, operation).assert_not_called()
                getattr(manager.using.return_value, operation).assert_not_called()
        self.managers[0].using.return_value.filter.assert_called_once_with(
            source_namespace=self.pin.spec.source_namespace,
            source_book_id=self.pin.spec.source_book_id,
        )
        self.managers[1].using.return_value.filter.assert_called_once_with(
            work_id=99,
            edition_key=self.pin.spec.edition_key,
        )
        headings = self.managers[2].using.return_value.filter
        headings.assert_called_once_with(edition_id=EDITION_ID)
        headings.return_value.order_by.assert_called_once_with("source_order", "source_row_id")
        self.assertIn("title_normalized", self.values[2].call_args.args)
        self.assertIn("parent__edition_id", self.values[2].call_args.args)

    def test_missing_work_or_wrong_edition_never_reads_unpinned_headings(self):
        from dataclasses import replace

        self.rows = replace(self.rows, works=())
        self.assertEqual(self.check().reason, "work_not_connected")
        self.managers[1].using.assert_not_called()
        self.managers[2].using.assert_not_called()
        self.rows = snapshot()
        self.rows.editions[0]["id"] += 1
        self.assertEqual(self.check().reason, "edition_not_connected")
        self.managers[2].using.assert_not_called()

    def test_corrupt_declared_count_does_not_expand_row_bound(self):
        self.rows.editions[0]["heading_count"] = 2**31
        self.assertEqual(self.check().reason, "edition_metadata")
        self.values[2].return_value.__getitem__.assert_called_once_with(slice(None, 5))

    def test_non_pg_or_nested_or_manual_transaction_is_closed_before_orm(self):
        for vendor, nested, autocommit in (
            ("sqlite", False, True),
            ("postgresql", True, True),
            ("postgresql", False, False),
        ):
            with self.subTest(vendor=vendor, nested=nested, autocommit=autocommit):
                self.connection.vendor = vendor
                self.connection.in_atomic_block = nested
                self.connection.get_autocommit.return_value = autocommit
                self.assertEqual(self.check().status, "NOT_CONNECTED")
        self.atomic.assert_not_called()
        self.connection.cursor.assert_not_called()
        self.managers[0].using.assert_not_called()

    def test_invalid_pin_precedes_connection_access(self):
        with patch("django.db.connections", None), self.assertRaises(ValueError):
            self.reader.read(self.pin, True)
        self.connection.get_autocommit.assert_not_called()

    def test_connection_and_query_failures_return_not_connected_without_details(self):
        from django.db import DatabaseError

        self.connection.get_autocommit.side_effect = DatabaseError("SYNTHETIC_SECRET")
        self.assertEqual(self.check().status, "NOT_CONNECTED")
        self.atomic.assert_not_called()
        self.connection.get_autocommit.side_effect = None
        self.values[2].return_value.__getitem__.side_effect = DatabaseError("SYNTHETIC_SECRET")
        result = self.check()
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertNotIn("SYNTHETIC_SECRET", repr(result))

    def test_transaction_exit_failure_cannot_return_consistent(self):
        from django.db import DatabaseError

        @contextmanager
        def failing_exit(**kwargs):
            self.active = True
            yield
            self.active = False
            raise DatabaseError("SYNTHETIC_SECRET")

        self.atomic.side_effect = failing_exit
        self.assertEqual(self.check().status, "NOT_CONNECTED")

    def test_unknown_alias_and_unconfigured_settings_are_closed(self):
        from django.core.exceptions import ImproperlyConfigured
        from django.utils.connection import ConnectionDoesNotExist

        for error in (
            ConnectionDoesNotExist("synthetic"),
            ImproperlyConfigured("SYNTHETIC_SECRET"),
        ):
            connections = MagicMock()
            connections.__getitem__.side_effect = error
            with patch("django.db.connections", connections):
                self.assertEqual(self.check().status, "NOT_CONNECTED")
        self.atomic.assert_not_called()
