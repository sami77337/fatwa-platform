"""Mocked command/transaction regressions; no real DB and no Django test runner."""

import importlib
import io
import json
import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import django
from django.core.management.base import CommandError

from tests.fiqh_import.test_catalog_audit import synthetic_catalog


def setUpModule():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    django.setup()


class ReadOnlySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("tools.fiqh_import.postgres")
        self.cursor = MagicMock()
        self.cursor.fetchone.return_value = ("on",)
        self.database = MagicMock(
            vendor="postgresql", in_atomic_block=False, alias="default", pg_version=180006,
        )
        self.database.get_autocommit.return_value = True
        self.database.cursor.return_value.__enter__.return_value = self.cursor
        self.connection_patch = patch.object(self.module, "connection", self.database)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.atomic = patch.object(self.module.transaction, "atomic", return_value=nullcontext())
        self.atomic_mock = self.atomic.start()
        self.addCleanup(self.atomic.stop)

    def test_read_only_repeatable_snapshot_is_set_before_caller_reads(self):
        with self.module.read_only_snapshot() as database:
            self.assertIs(database, self.database)
            self.assertEqual(self.cursor.execute.call_args_list[0].args, (
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
            ))
            self.assertEqual(self.cursor.execute.call_args_list[1].args, ("SHOW transaction_read_only",))
        self.atomic_mock.assert_called_once_with(using="default")

    def test_unconfirmed_read_only_transaction_is_rejected(self):
        self.cursor.fetchone.return_value = ("off",)
        with self.assertRaises(self.module.ReadOnlySnapshotError):
            with self.module.read_only_snapshot():
                self.fail("Unconfirmed transaction must not reach an ORM read")

    def test_nested_manual_non_postgres_or_unsupported_version_is_rejected(self):
        for changes in (
            {"in_atomic_block": True}, {"vendor": "sqlite"}, {"pg_version": 160000},
            {"pg_version": 190000},
        ):
            with self.subTest(changes=changes), patch.multiple(self.database, **changes):
                with self.assertRaises(self.module.ReadOnlySnapshotError):
                    with self.module.read_only_snapshot():
                        self.fail("Unsafe transaction must be refused")
        self.database.get_autocommit.return_value = False
        with self.assertRaises(self.module.ReadOnlySnapshotError):
            with self.module.read_only_snapshot():
                self.fail("Manual outer transaction must be refused")


class AuditCommandTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("apps.reference.management.commands.audit_book622")
        self.prepared, metadata, self.rows = synthetic_catalog()
        spec = self.prepared.spec
        self.edition = SimpleNamespace(
            pk=70, work=SimpleNamespace(
                source_namespace=spec.source_namespace, source_book_id=spec.source_book_id,
                title_original=spec.work_title, madhhab=spec.madhhab,
            ), edition_key=spec.edition_key, title=spec.edition_title, publisher=spec.publisher,
            source_archive_sha256=spec.source_archive_sha256,
            source_input_sha256=spec.source_input_sha256, input_name=spec.input_name,
            ingest_checksum=self.prepared.checksum, heading_count=7, root_count=2, max_depth=5,
        )
        self.options = {"archive": "synthetic-never-read.zip", "edition": 70, "max_issues": 20, "heading_id": None}
        self.stdout = io.StringIO()
        self.command = self.module.Command(stdout=self.stdout)

    def test_invalid_options_fail_before_source_or_database_access(self):
        for changes in ({"max_issues": 0}, {"max_issues": 101}, {"edition": 0}, {"heading_id": 0}):
            with self.subTest(changes=changes), patch.object(self.module, "validate_book622") as source:
                with self.assertRaises(CommandError):
                    self.command.handle(**{**self.options, **changes})
                source.assert_not_called()

    def test_bad_source_never_opens_a_database_snapshot(self):
        with patch.object(self.module, "validate_book622", side_effect=ValueError("wrong source")), patch.object(
            self.module, "read_only_snapshot"
        ) as snapshot:
            with self.assertRaises(CommandError):
                self.command.handle(**self.options)
            snapshot.assert_not_called()

    def run_mocked(self, heading_id=None):
        edition_manager = MagicMock()
        edition_manager.select_related.return_value.filter.return_value.first.return_value = self.edition
        row_manager = MagicMock()
        query = row_manager.filter.return_value.annotate.return_value.order_by.return_value.values.return_value
        query.__getitem__.return_value.iterator.return_value = iter(self.rows)
        with patch.object(self.module, "validate_book622", return_value=(self.prepared, {"fixture": "synthetic"})), patch.object(
            self.module, "read_only_snapshot", return_value=nullcontext(SimpleNamespace(pg_version=180006))
        ), patch.object(self.module.ReferenceEdition, "objects", edition_manager), patch.object(
            self.module.ReferenceHeading, "objects", row_manager
        ):
            self.command.handle(**{**self.options, "heading_id": heading_id})
        # ORM chain has only reads; comparator was real, not mocked.
        edition_manager.create.assert_not_called()
        row_manager.create.assert_not_called()
        row_manager.bulk_create.assert_not_called()
        return json.loads(self.stdout.getvalue())

    def test_successful_full_comparison_has_no_import_and_no_bulk_titles(self):
        report = self.run_mocked()
        self.assertEqual(report["matched_rows"], 7)
        self.assertEqual(report["database_import"], "NOT_RUN")
        self.assertNotIn("عُنْوان", self.stdout.getvalue())

    def test_drift_is_failure_with_bounded_report_and_no_repair(self):
        self.rows[2]["source_page_number"] += 1
        with self.assertRaisesRegex(CommandError, "mismatch"):
            self.run_mocked()
        report = json.loads(self.stdout.getvalue())
        self.assertFalse(report["valid"])
        self.assertEqual(report["field_mismatches"]["source_page_number"], 1)
        self.assertEqual(report["database_import"], "NOT_RUN")

    def test_optional_citation_uses_existing_bounded_path_service(self):
        heading = SimpleNamespace(
            source_id="622-3", source_row_id=3, title_original="عنوان اصطناعي",
            source_part="01", source_page_number=23, source_page_id=103,
        )
        ancestors = [{"id": 2, "title": "جذر اصطناعي"}, {"id": 3, "title": heading.title_original}]
        with patch.object(self.module, "node", return_value=heading) as node, patch.object(
            self.module, "heading_path", return_value=ancestors
        ) as path:
            report = self.run_mocked(heading_id=3)
        node.assert_called_once_with(self.edition, 3)
        path.assert_called_once_with(self.edition, heading)
        self.assertEqual(report["citation"]["part"], "01")
        self.assertEqual(report["citation"]["path"], ancestors)


class ImportPreviewSafetyTests(unittest.TestCase):
    def test_apply_without_checksum_and_checksum_without_apply_fail_before_validation(self):
        module = importlib.import_module("apps.reference.management.commands.import_book622")
        for changes in (
            {"apply": True, "expected_checksum": None},
            {"apply": False, "expected_checksum": "0" * 64},
            {"apply": True, "validate_only": True, "expected_checksum": "0" * 64},
        ):
            options = {"archive": "never-read.zip", "validate_only": False, "apply": False, "expected_checksum": None, **changes}
            with self.subTest(changes=changes), patch.object(module, "ingest_catalog") as ingest, patch.object(
                module, "validate_book622"
            ) as source:
                with self.assertRaises(CommandError):
                    module.Command().handle(**options)
                source.assert_not_called()
                ingest.assert_not_called()

    def test_default_is_preview_and_validate_only_never_calls_persistence(self):
        module = importlib.import_module("apps.reference.management.commands.import_book622")
        prepared, _, _ = synthetic_catalog()
        for validate_only in (False, True):
            output = io.StringIO()
            with self.subTest(validate_only=validate_only), patch.object(
                module, "validate_book622", return_value=(prepared, {})
            ), patch.object(module.Command, "check"), patch.object(module, "ingest_catalog") as ingest:
                # Never execute the persistence function, including its write path.
                from apps.reference.ingest import IngestResult
                ingest.return_value = IngestResult(True, True, prepared.checksum, 7, 70)
                module.Command(stdout=output).handle(
                    archive="never-read.zip", validate_only=validate_only, apply=False,
                    expected_checksum=None,
                )
                if validate_only:
                    ingest.assert_not_called()
                else:
                    self.assertTrue(ingest.call_args.kwargs["dry_run"])
                    self.assertEqual(json.loads(output.getvalue())["database_import"], "PREVIEW_ONLY")


class BenchmarkCommandTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("apps.reference.management.commands.benchmark_reference")

    def test_bounds_and_empty_search_fail_before_database_access(self):
        options = {"edition": 1, "query": "كتاب", "repeats": 2, "expected_headings": 11397, "heading_id": 1}
        for changes in ({"repeats": 0}, {"repeats": 21}, {"expected_headings": 10}, {"heading_id": 0}, {"query": "ـ"}, {"query": "x" * 161}):
            with self.subTest(changes=changes), patch.object(self.module, "read_only_snapshot") as snapshot:
                with self.assertRaises(CommandError):
                    self.module.Command().handle(**{**options, **changes})
                snapshot.assert_not_called()

    def test_measure_executes_each_call_and_records_materialized_page_counts(self):
        page = SimpleNamespace(items=[{"id": i} for i in range(30)], total=32)
        operation = MagicMock(return_value=page)
        capture = MagicMock()
        capture.__enter__.return_value = ["count query", "materialized page query"]
        with patch.object(self.module, "CaptureQueriesContext", return_value=capture):
            result = self.module._measure(operation, 3)
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(result["returned_items"], [30, 30, 30])
        self.assertEqual(result["total_matches"], [32, 32, 32])
        self.assertEqual(result["query_counts"], [2, 2, 2])
        self.assertEqual(len(result["latency_ms"]), 3)
        self.assertGreaterEqual(result["median_ms"], 0)

    def test_measure_rejects_inconsistent_materialized_results(self):
        operation = MagicMock(side_effect=[[1], [1, 2]])
        with patch.object(self.module, "CaptureQueriesContext"):
            with self.assertRaisesRegex(CommandError, "changed"):
                self.module._measure(operation, 2)


if __name__ == "__main__":
    unittest.main()
