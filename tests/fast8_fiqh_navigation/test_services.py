"""Exercise the new topology/evidence join, not a replacement navigation algorithm."""

from contextlib import contextmanager
from dataclasses import asdict, replace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.fast8_fiqh_navigation.services import CatalogNavigation, CatalogSnapshot
from apps.reference.records import prepare_catalog
from apps.reference_links.resolution import CatalogReadError, SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture


class Reader:
    def __init__(self, prepared, headings, edition=EDITION_ID):
        self.value = CatalogSnapshot(edition, prepared, SnapshotCatalog(headings))
        self.active = False

    @contextmanager
    def snapshot(self, edition_id):
        self.active = True
        try:
            yield self.value
        finally:
            self.active = False


class NavigationTests(TestCase):
    def setUp(self):
        self.prepared, self.headings = synthetic_fixture()
        self.adapter = CatalogNavigation(self.prepared, EDITION_ID)
        self.query = {"edition": str(EDITION_ID), "source_row_id": "40"}
        self.reader = Reader(self.prepared, self.headings)

    def assert_closed(self, result):
        self.assertEqual(result.trail.status, "unverified")
        self.assertIsNone(result.edition_title)
        self.assertIsNone(result.publisher)
        self.assertIsNone(result.trail.current)
        self.assertEqual(result.trail.breadcrumbs, ())
        for field in ("previous", "next", "catalog_return_url", "research_return_url"):
            self.assertIsNone(getattr(result.trail, field))

    def test_exact_heading_returns_live_verified_edition_and_source_order(self):
        result = self.adapter.navigate(self.query, self.reader)
        self.assertEqual(result.trail.status, "verified")
        self.assertEqual(result.edition_title, self.prepared.spec.edition_title)
        self.assertEqual(result.publisher, self.prepared.spec.publisher)
        self.assertEqual(result.trail.current.evidence, self.headings[2])
        self.assertEqual(result.trail.current.evidence.heading_title, "  فَصْلٌ <اصطناعي> e\u0301  ")
        self.assertEqual([x.evidence.source_row_id for x in result.trail.breadcrumbs], [1, 2, 40])
        self.assertEqual(result.trail.previous.evidence.source_row_id, 2)
        self.assertEqual(result.trail.next.evidence.source_row_id, 41)
        self.assertFalse(self.reader.active)

    def test_all_evidence_reads_remain_inside_snapshot(self):
        catalog = self.reader.value.evidence
        evidence = Mock()

        def lookup(edition, row):
            self.assertTrue(self.reader.active)
            return catalog.lookup(edition, row)

        evidence.lookup.side_effect = lookup
        self.reader.value = replace(self.reader.value, evidence=evidence)
        self.assertEqual(self.adapter.navigate(self.query, self.reader).trail.status, "verified")
        self.assertGreater(evidence.lookup.call_count, 0)

    def test_no_implicit_database_or_edition_selection(self):
        self.assertEqual(self.adapter.navigate(self.query).trail.reason, "NOT_CONNECTED")
        reader = Mock()
        result = self.adapter.navigate({**self.query, "edition": "7002"}, reader)
        self.assert_closed(result)
        reader.snapshot.assert_not_called()

    def test_invalid_or_ambiguous_queries_never_open_snapshot(self):
        from django.http import QueryDict

        reader = Mock()
        bad = [None, {}, {**self.query, "title": "باب"}, {"source_row_id": "40"}]
        for key in self.query:
            for value in (None, True, 40, "", "-1", "0", "٤٠", "+40", " 40", "1.0", "9" * 21):
                bad.append({**self.query, key: value})
        with patch("django.http.request.settings", Mock(DATA_UPLOAD_MAX_NUMBER_FIELDS=1000)):
            bad.append(QueryDict("edition=7001&edition=7002&source_row_id=40", encoding="utf-8"))
        for query in bad:
            with self.subTest(query=query):
                self.assert_closed(self.adapter.navigate(query, reader))
        reader.snapshot.assert_not_called()

    def test_every_metadata_field_is_pinned_not_only_public_evidence(self):
        for name in self.prepared.spec.__dataclass_fields__:
            old = getattr(self.prepared.spec, name)
            if name.startswith("expected_"):
                continue
            value = "c" * 64 if name.endswith("sha256") else old + "-changed"
            altered = prepare_catalog(
                replace(self.prepared.spec, **{name: value}), self.prepared.records
            )
            with self.subTest(name=name):
                self.assert_closed(
                    self.adapter.navigate(self.query, Reader(altered, self.headings))
                )

    def test_unrelated_row_identity_and_order_changes_close_whole_result(self):
        # Row 10 is neither the selected heading nor its neighboring path.
        for name, value in (
            ("source_id", "other"),
            ("source_page_id", 999),
            ("source_entry_number", 2),
            ("title_original", "عنوان اصطناعي آخر"),
            ("source_order", 85),
            ("position", 99),
            ("parent_source_row_id", 1),
            ("source_part", "آخر"),
            ("source_page_number", 99),
        ):
            records = self.prepared.records[:-1] + (
                replace(self.prepared.records[-1], **{name: value}),
            )
            altered = prepare_catalog(self.prepared.spec, records)
            with self.subTest(name=name):
                self.assert_closed(
                    self.adapter.navigate(self.query, Reader(altered, self.headings))
                )

    def test_invalid_snapshot_types_checksum_and_strict_numeric_identity(self):
        snapshots = [
            None,
            replace(self.reader.value, edition_id=True),
            replace(self.reader.value, edition_id=7001.0),
            replace(self.reader.value, edition_id=7002),
            replace(self.reader.value, prepared=replace(self.prepared, checksum="c" * 64)),
            replace(
                self.reader.value,
                prepared=replace(self.prepared, records=self.prepared.records[:-1]),
            ),
        ]
        for snapshot in snapshots:
            self.reader.value = snapshot
            self.assert_closed(self.adapter.navigate(self.query, self.reader))

    def test_correct_topology_cannot_promote_missing_or_changed_evidence(self):
        for headings in (
            self.headings[:2] + self.headings[3:],
            self.headings[:2] + (replace(self.headings[2], printed_page=99),) + self.headings[3:],
        ):
            self.assert_closed(self.adapter.navigate(self.query, Reader(self.prepared, headings)))

    def test_research_origin_rechecked_even_at_another_heading(self):
        query = {**self.query, "source_row_id": "9"}
        case = synthetic_case()
        result = self.adapter.from_reference(query, case, 1, self.reader)
        self.assertEqual(result.trail.status, "verified")
        self.assertEqual(
            result.trail.research_return_url, "/dev/research-bridge/intake-1#reference-1"
        )
        self.assertEqual(result.trail.current.evidence.source_row_id, 9)
        self.assert_closed(
            self.adapter.from_reference(query, case, 1, Reader(self.prepared, self.headings[1:]))
        )
        self.assert_closed(self.adapter.from_reference(query, None, None, self.reader))

    def test_reader_entry_and_exit_failures_withhold_all_metadata(self):
        for at_exit in (False, True):

            class Broken:
                @contextmanager
                def snapshot(inner, edition):
                    if not at_exit:
                        raise CatalogReadError("synthetic-secret-detail")
                    yield self.reader.value
                    raise CatalogReadError("synthetic-secret-detail")

            result = self.adapter.navigate(self.query, Broken())
            self.assert_closed(result)
            self.assertNotIn("synthetic-secret-detail", str(asdict(result)))

    def test_unconfigured_django_reader_is_unavailable_without_details(self):
        from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured

        reader = Mock()
        for error in (AppRegistryNotReady, ImproperlyConfigured):
            reader.snapshot.side_effect = error("synthetic-secret-detail")
            result = self.adapter.navigate(self.query, reader)
            self.assert_closed(result)
            self.assertEqual(result.trail.reason, "catalog_unavailable")
            self.assertNotIn("synthetic-secret-detail", str(asdict(result)))
