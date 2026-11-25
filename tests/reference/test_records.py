"""Pure contract tests. All records are synthetic, not owner-source acceptance."""
import unittest
from dataclasses import replace

from apps.reference.normalization import normalize_title
from apps.reference.query import InvalidQuery, Page, bounded_int, validate_search
from apps.reference.records import CatalogSpec, HeadingRecord, InvalidCatalog, prepare_catalog


def synthetic_spec() -> CatalogSpec:
    return CatalogSpec(
        source_namespace="synthetic", source_book_id="test-book", work_title="مرجع اصطناعي",
        madhhab="اختبار", edition_key="test", edition_title="طبعة اختبار", publisher="اختبار",
        source_archive_sha256="a" * 64, source_input_sha256="b" * 64, input_name="synthetic.jsonl",
        expected_rows=2, expected_roots=1, expected_max_depth=2,
    )


def synthetic_rows() -> tuple[HeadingRecord, ...]:
    return (
        HeadingRecord("test-1", 1, None, 1, 1, 1, 10, "مقدمة اصطناعية", 5, "عنوان اصطناعي"),
        HeadingRecord("test-2", 2, 1, 2, 1, 2, 11, "مقدمة اصطناعية", 6, "فَرْعٌ تَجْرِيبِيّ"),
    )


class RecordsTests(unittest.TestCase):
    def test_original_title_and_part_are_preserved(self):
        prepared = prepare_catalog(synthetic_spec(), synthetic_rows())
        self.assertEqual(prepared.records[1].title_original, "فَرْعٌ تَجْرِيبِيّ")
        self.assertEqual(prepared.records[1].source_part, "مقدمة اصطناعية")

    def test_checksum_is_deterministic_and_input_sensitive(self):
        spec, rows = synthetic_spec(), synthetic_rows()
        first = prepare_catalog(spec, rows)
        self.assertEqual(first.checksum, prepare_catalog(spec, rows[::-1]).checksum)
        changed = (rows[0], replace(rows[1], title_original="عنوان آخر اصطناعي"))
        self.assertNotEqual(first.checksum, prepare_catalog(spec, changed).checksum)
        self.assertNotEqual(first.checksum, prepare_catalog(replace(spec, source_input_sha256="c" * 64), rows).checksum)

    def test_invalid_source_invariants_are_rejected(self):
        spec, rows = synthetic_spec(), synthetic_rows()
        changes = [
            {"parent_source_row_id": 999}, {"parent_source_row_id": 2}, {"depth": 1},
            {"source_id": "test-1"}, {"source_row_id": 1}, {"source_order": 1},
            {"source_part": ""}, {"source_page_id": 0}, {"source_page_number": 0},
            {"title_original": " "}, {"source_row_id": True}, {"source_entry_number": 0},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(InvalidCatalog):
                prepare_catalog(spec, (rows[0], replace(rows[1], **change)))

    def test_profile_and_digest_and_local_path_are_rejected(self):
        for change in [{"expected_rows": 3}, {"expected_roots": 2}, {"expected_max_depth": 5},
                       {"source_archive_sha256": "invalid"}, {"input_name": "C:/private/input.jsonl"}]:
            with self.subTest(change=change), self.assertRaises(InvalidCatalog):
                prepare_catalog(replace(synthetic_spec(), **change), synthetic_rows())

    def test_arabic_normalization_is_search_only(self):
        self.assertEqual(normalize_title("  إِمْلَاءٌ   آمنـ  "), "املاء امن")
        # Deliberately do not merge ta marbuta/ha or hamza carriers.
        self.assertNotEqual(normalize_title("رحمة"), normalize_title("رحمه"))
        self.assertEqual(normalize_title("100%_"), "100%_")

    def test_request_bounds(self):
        for value in ["-1", "1.0", "1e3", "١", " 1", "9" * 100, "0", "101"]:
            with self.subTest(value=value), self.assertRaises(InvalidQuery):
                bounded_int(value, 1, 100)
        self.assertEqual(bounded_int("100", 1, 100), 100)
        with self.assertRaises(InvalidQuery):
            Page(limit=101)
        for text, mode in [("x" * 161, "literal"), ("x " * 11, "normalized"), ("\x00", "exact"), ("x", "semantic")]:
            with self.subTest(text=text, mode=mode), self.assertRaises(InvalidQuery):
                validate_search(text, mode)
