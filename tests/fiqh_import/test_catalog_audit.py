"""Synthetic, database-free audit regressions; never real-source acceptance."""

import json
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

from apps.reference.normalization import normalize_title
from apps.reference.records import CatalogSpec, HeadingRecord, InvalidCatalog, prepare_catalog
from tools.fiqh_import.audit import HISTORICAL_FIELDS, audit_catalog, expected_metadata


def synthetic_catalog():
    parents = (None, None, 2, 3, 4, 5, 2)
    depths = (1, 1, 2, 3, 4, 5, 2)
    records = tuple(
        HeadingRecord(
            source_id=f"622-{ident}", source_row_id=ident,
            parent_source_row_id=parent, source_order=ident,
            position=2 if ident in (2, 7) else 1, depth=depth,
            source_page_id=100 + ident, source_part="المقدمة" if ident == 1 else "01",
            source_page_number=20 + ident, title_original=f"عُنْوان اصطناعي {ident}",
            source_entry_number=None if ident == 1 else ident,
        )
        for ident, (parent, depth) in enumerate(zip(parents, depths, strict=True), 1)
    )
    spec = CatalogSpec(
        source_namespace="synthetic", source_book_id="622", work_title="عمل اصطناعي",
        madhhab="Synthetic only", edition_key="synthetic-test", edition_title="طبعة اصطناعية",
        publisher="Synthetic publisher", source_archive_sha256="0" * 64,
        source_input_sha256="1" * 64, input_name="synthetic-only.jsonl",
        expected_rows=7, expected_roots=2, expected_max_depth=5,
    )
    prepared = prepare_catalog(spec, records)
    metadata = {"edition_id": 70, **expected_metadata(prepared)}
    rows = [
        {**asdict(row), "title_normalized": normalize_title(row.title_original),
         "parent_edition_id": 70 if row.parent_source_row_id is not None else None}
        for row in records
    ]
    return prepared, metadata, rows


class CatalogAuditTests(unittest.TestCase):
    def setUp(self):
        self.prepared, self.metadata, self.rows = synthetic_catalog()

    def audit(self, rows=None, **options):
        return audit_catalog(
            self.prepared, self.metadata, self.rows if rows is None else rows, **options
        )

    def test_full_comparison_is_deterministic_idempotent_and_does_not_mutate_inputs(self):
        before = json.dumps([self.metadata, self.rows], ensure_ascii=False, sort_keys=True)
        first, second = self.audit(), self.audit()
        self.assertEqual(first, second)
        self.assertTrue(first["valid"])
        self.assertEqual(first["matched_rows"], 7)
        self.assertEqual((first["actual_roots"], first["actual_max_depth"]), (2, 5))
        self.assertEqual(first["historical_fields_compared"], list(HISTORICAL_FIELDS))
        self.assertEqual(first["database_import"], "NOT_RUN")
        self.assertEqual(
            before, json.dumps([self.metadata, self.rows], ensure_ascii=False, sort_keys=True)
        )

    def test_every_historical_field_and_normalized_title_is_compared(self):
        changes = {
            "source_id": "622-999", "source_row_id": 999, "parent_source_row_id": 999,
            "source_order": 999, "position": 999, "depth": 5, "source_page_id": 999,
            "source_part": "1", "source_page_number": 999,
            "title_original": "عنوان اصطناعي 3", "source_entry_number": None,
            "title_normalized": "altered",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                rows = [dict(row) for row in self.rows]
                rows[2][field] = value
                report = self.audit(rows)
                self.assertFalse(report["valid"])
                if field != "source_row_id":
                    self.assertEqual(report["field_mismatches"][field], 1)

    def test_matching_stored_checksum_never_skips_row_comparison(self):
        self.rows[-1]["title_original"] += " changed"
        self.assertEqual(self.metadata["ingest_checksum"], self.prepared.checksum)
        self.assertFalse(self.audit()["valid"])

    def test_truncated_snapshot_fails_without_repair(self):
        report = self.audit(self.rows[:-1])
        self.assertEqual(report["missing_rows"], 1)
        self.assertEqual(report["issue_counts"]["MISSING_SOURCE_ROW"], 1)
        self.assertEqual(report["issue_counts"]["HEADING_COUNT"], 1)

    def test_duplicate_and_unexpected_ids_fail(self):
        duplicate = self.audit(self.rows + [dict(self.rows[2])])
        self.assertEqual(duplicate["issue_counts"]["DUPLICATE_SOURCE_ROW_ID"], 1)
        self.rows[-1]["source_row_id"] = 999
        unexpected = self.audit()
        self.assertEqual(unexpected["issue_counts"]["UNEXPECTED_SOURCE_ROW"], 1)
        self.assertEqual(unexpected["missing_rows"], 1)

    def test_orphan_and_cross_edition_parent_cannot_hide_behind_same_row_id(self):
        self.rows[2]["parent_source_row_id"] = 999
        self.assertFalse(self.audit()["valid"])
        self.rows[2]["parent_source_row_id"] = 2
        self.rows[2]["parent_edition_id"] = 71
        report = self.audit()
        self.assertEqual(report["field_mismatches"]["parent_edition_id"], 1)

    def test_missing_nullable_field_and_numeric_coercion_are_not_equal(self):
        del self.rows[0]["source_entry_number"]
        self.rows[0]["source_order"] = True
        self.rows[1]["source_row_id"] = True
        report = self.audit()
        self.assertFalse(report["valid"])
        self.assertIn("source_entry_number", report["field_mismatches"])
        self.assertIn("source_order", report["field_mismatches"])
        self.assertIn("INVALID_SOURCE_ROW_ID", report["issue_counts"])

    def test_all_work_edition_identity_fields_and_counts_are_immutable(self):
        for field in expected_metadata(self.prepared):
            with self.subTest(field=field):
                metadata = dict(self.metadata)
                value = metadata[field]
                metadata[field] = value + 1 if type(value) is int else value + " changed"
                report = audit_catalog(self.prepared, metadata, self.rows)
                self.assertEqual(report["issue_counts"]["METADATA_MISMATCH"], 1)
                self.assertIn(field, report["issues"][0]["fields"])

    def test_diagnostics_are_bounded_and_never_export_titles(self):
        for row in self.rows:
            row["title_original"] += " changed"
        report = self.audit(max_issues=2)
        self.assertEqual(len(report["issues"]), 2)
        self.assertEqual(report["issue_count"], 7)
        self.assertEqual(report["issues_omitted"], 5)
        self.assertNotIn("عُنْوان", json.dumps(report, ensure_ascii=False))

    def test_scan_of_unexpected_snapshot_is_bounded_and_fails_closed(self):
        with patch("tools.fiqh_import.audit.MAX_ROWS", 5):
            report = self.audit(iter(self.rows))
        self.assertFalse(report["scan_complete"])
        self.assertEqual(report["scanned_rows"], 6)
        self.assertIn("ROW_LIMIT_EXCEEDED", report["issue_counts"])

    def test_changed_prepared_checksum_is_rejected(self):
        with self.assertRaises(InvalidCatalog):
            audit_catalog(replace(self.prepared, checksum="0" * 64), self.metadata, self.rows)

    def test_invalid_diagnostic_bounds_fail_before_scan(self):
        for value in (0, 101, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.audit(max_issues=value)


if __name__ == "__main__":
    unittest.main()
