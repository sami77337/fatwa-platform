"""Exact hierarchy and source-order navigation without persistence."""

from dataclasses import asdict, replace
from unittest import TestCase
from unittest.mock import Mock

from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference.records import prepare_catalog
from apps.reference_links.resolution import KIND, CatalogReadError, SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture


class TrailTests(TestCase):
    def setUp(self):
        self.prepared, self.headings = synthetic_fixture()
        self.catalog = SnapshotCatalog(self.headings)
        self.trail = ReadingTrail(self.prepared, EDITION_ID)

    def assert_closed(self, result):
        self.assertEqual(result.status, "unverified")
        self.assertTrue(result.reason)
        self.assertEqual(result.kind, KIND)
        self.assertIsNone(result.current)
        self.assertEqual(result.breadcrumbs, ())
        self.assertIsNone(result.previous)
        self.assertIsNone(result.next)
        self.assertIsNone(result.catalog_return_url)
        self.assertIsNone(result.research_return_url)

    def test_exact_breadcrumb_ids_text_pins_and_printed_locations(self):
        result = self.trail.navigate(42, self.catalog)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.kind, KIND)
        self.assertEqual(
            [item.evidence.source_row_id for item in result.breadcrumbs], [1, 2, 40, 41, 42]
        )
        self.assertEqual(
            tuple(item.evidence.heading_title for item in result.breadcrumbs), self.headings[4].path
        )
        self.assertEqual(result.current.evidence, self.headings[4])
        for item in result.breadcrumbs:
            self.assertEqual(
                item.catalog_url, f"/fiqh/nodes/{item.evidence.source_row_id}?edition=7001"
            )
            self.assertEqual(item.evidence.edition_key, self.prepared.spec.edition_key)
            self.assertEqual(item.evidence.source_input_sha256, "b" * 64)
            self.assertEqual(item.evidence.source_archive_sha256, "a" * 64)
        self.assertIn("&lt;اصطناعي&gt;", result.breadcrumbs[2].citation)
        self.assertEqual(result.breadcrumbs[2].evidence.printed_part, "تمهيد")
        self.assertEqual(result.breadcrumbs[2].evidence.printed_page, 3)

    def test_order_is_source_order_not_id_page_title_or_input_order(self):
        expected = [1, 2, 40, 41, 42, 3, 8, 9, 10]
        shuffled = prepare_catalog(self.prepared.spec, self.prepared.records[::-1])
        trail = ReadingTrail(shuffled, EDITION_ID)
        for index, ident in enumerate(expected):
            result = trail.navigate(ident, SnapshotCatalog(self.headings[::-1]))
            self.assertEqual(result.status, "verified")
            self.assertEqual(
                result.previous.evidence.source_row_id if result.previous else None,
                expected[index - 1] if index else None,
            )
            self.assertEqual(
                result.next.evidence.source_row_id if result.next else None,
                expected[index + 1] if index + 1 < len(expected) else None,
            )

    def test_duplicate_titles_keep_exact_parent_id(self):
        left = self.trail.navigate(2, self.catalog)
        right = self.trail.navigate(9, self.catalog)
        self.assertEqual(left.current.evidence.heading_title, right.current.evidence.heading_title)
        self.assertEqual([x.evidence.source_row_id for x in right.breadcrumbs], [8, 9])
        self.assertNotEqual(left.current.catalog_url, right.current.catalog_url)

    def test_missing_neighbor_is_not_skipped_or_displayed(self):
        for missing in (1, 2, 41):
            with self.subTest(missing=missing):
                catalog = SnapshotCatalog(
                    tuple(x for x in self.headings if x.source_row_id != missing)
                )
                self.assert_closed(self.trail.navigate(40, catalog))

    def test_ambiguous_unavailable_and_missing_catalog_fail_closed(self):
        self.assert_closed(self.trail.navigate(40, SnapshotCatalog(())))
        self.assert_closed(
            self.trail.navigate(40, SnapshotCatalog(self.headings + (self.headings[2],)))
        )
        catalog = Mock()
        catalog.lookup.side_effect = CatalogReadError("private connection detail")
        result = self.trail.navigate(40, catalog)
        self.assert_closed(result)
        self.assertNotIn("private", str(asdict(result)))

    def test_invalid_ids_never_query_catalog(self):
        catalog = Mock()
        for ident in (True, False, 0, -1, 1.0, "1", None, 2**63, 999):
            with self.subTest(ident=ident):
                self.assert_closed(self.trail.navigate(ident, catalog))
        catalog.lookup.assert_not_called()

    def test_every_catalog_pin_and_metadata_mismatch_hides_all_links(self):
        for field, value in (
            ("edition_id", 7002),
            ("source_row_id", 999),
            ("source_namespace", "other"),
            ("source_book_id", "623"),
            ("source_input_sha256", "c" * 64),
            ("source_archive_sha256", None),
            ("edition_key", None),
            ("edition_key", "other"),
            ("work_title", "آخر"),
            ("heading_title", "آخر"),
            ("path", ("آخر", self.headings[2].heading_title)),
            ("printed_part", "ثان"),
            ("printed_page", None),
            ("printed_page", 99),
        ):
            with self.subTest(field=field, value=value):
                altered = replace(self.headings[2], **{field: value})
                catalog = Mock()
                catalog.lookup.side_effect = lambda edition, row: (
                    (altered,) if row == 40 else self.catalog.lookup(edition, row)
                )
                self.assert_closed(self.trail.navigate(40, catalog))

    def test_verified_reference_preserves_original_return_occurrence_after_navigation(self):
        case = synthetic_case()
        before = asdict(case)
        result = self.trail.from_reference(case, 1, self.catalog, source_row_id=42)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.current.evidence.source_row_id, 42)
        self.assertEqual(result.research_return_url, "/dev/research-bridge/intake-1#reference-1")
        self.assertIn("edition=7001", result.catalog_return_url)
        self.assertEqual(asdict(case), before)

    def test_unverified_reference_cannot_be_promoted_by_matching_catalog(self):
        case = synthetic_case()
        catalog = Mock()
        for changes in (
            {"status": "unresolved"},
            {"raw_status": "unverified"},
            {"contract_status": "UNVERIFIED"},
            {"reasons": ("conflict",)},
            {"verified_identity": "{}"},
            {"evidence": "null"},
        ):
            with self.subTest(changes=changes):
                bad_case = replace(case, references=(replace(case.references[0], **changes),))
                self.assert_closed(self.trail.from_reference(bad_case, 1, catalog))
        catalog.lookup.assert_not_called()

    def test_origin_is_rechecked_even_when_target_is_otherwise_valid(self):
        case = synthetic_case()
        catalog = SnapshotCatalog(tuple(x for x in self.headings if x.source_row_id != 1))
        self.assert_closed(self.trail.from_reference(case, 1, catalog, source_row_id=9))

    def test_invalid_case_keys_and_reference_ordinals_cannot_create_return_urls(self):
        case = synthetic_case()
        for key in ("//evil.example", "../escape", "a?edition=9", "a#ref", "a/b", "", "a%2fb"):
            with self.subTest(key=key):
                self.assert_closed(
                    self.trail.from_reference(
                        replace(case, case=replace(case.case, key=key)), 1, self.catalog
                    )
                )
        for ordinal in (True, 0, -1, "1", None, 999):
            with self.subTest(ordinal=ordinal):
                self.assert_closed(self.trail.from_reference(case, ordinal, self.catalog))

    def test_bad_edition_or_forged_prepared_catalog_is_rejected(self):
        for edition in (True, 0, -1, 1.0, "7001", None, 2**63):
            with self.subTest(edition=edition), self.assertRaises(ValueError):
                ReadingTrail(self.prepared, edition)
        for altered in (
            replace(self.prepared, checksum="c" * 64),
            replace(self.prepared, records=self.prepared.records[:-1]),
            replace(self.prepared, spec=replace(self.prepared.spec, source_book_id="623")),
            replace(
                self.prepared,
                records=(replace(self.prepared.records[0], parent_source_row_id=42),)
                + self.prepared.records[1:],
            ),
        ):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                ReadingTrail(altered, EDITION_ID)
