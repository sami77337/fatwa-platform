"""Negative navigation evidence, immutable outputs, bounds, and side-effect guards."""

from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference.records import PreparedCatalog, prepare_catalog
from apps.reference_links.resolution import SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture


class BoundaryTests(TestCase):
    def setUp(self):
        self.prepared, self.headings = synthetic_fixture()
        self.catalog = SnapshotCatalog(self.headings)
        self.trail = ReadingTrail(self.prepared, EDITION_ID)

    def test_service_has_no_file_database_network_or_process_operations(self):
        case = synthetic_case()
        with ExitStack() as stack:
            for target in (
                "builtins.open",
                "pathlib.Path.open",
                "socket.socket",
                "subprocess.Popen",
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            ):
                stack.enter_context(patch(target, side_effect=AssertionError(f"I/O: {target}")))
            trail = ReadingTrail(self.prepared, EDITION_ID)
            direct = trail.navigate(40, self.catalog)
            bridged = trail.from_reference(case, 1, self.catalog, source_row_id=9)
        self.assertEqual(direct.status, "verified")
        self.assertEqual(bridged.status, "verified")

    def test_caller_input_is_unchanged_and_result_cannot_be_mutated(self):
        before = asdict(self.prepared)
        result = self.trail.navigate(40, self.catalog)
        self.assertEqual(asdict(self.prepared), before)
        with self.assertRaises(FrozenInstanceError):
            result.current = None
        with self.assertRaises(FrozenInstanceError):
            result.current.catalog_url = "https://example.invalid"

    def test_lookup_budget_is_bounded_by_three_depth_five_paths(self):
        catalog = Mock(wraps=self.catalog)
        result = self.trail.navigate(42, catalog)
        self.assertEqual(result.status, "verified")
        self.assertLessEqual(catalog.lookup.call_count, 15)
        for call in catalog.lookup.call_args_list:
            self.assertEqual(call.args[0], EDITION_ID)

    def test_boolean_catalog_identity_is_not_equal_to_integer_identity(self):
        for field, value in (("source_row_id", True), ("edition_id", True), ("printed_page", True)):
            # Use edition/page 1 so dataclass equality alone would accept True.
            spec = replace(
                self.prepared.spec, expected_rows=1, expected_roots=1, expected_max_depth=1
            )
            record = replace(self.prepared.records[0], source_page_number=1)
            trail = ReadingTrail(prepare_catalog(spec, (record,)), 1)
            heading = replace(self.headings[0], edition_id=1, printed_page=1)
            with self.subTest(field=field):
                catalog = Mock()
                catalog.lookup.return_value = (replace(heading, **{field: value}),)
                result = trail.navigate(1, catalog)
                self.assertEqual(result.status, "unverified")
                self.assertIsNone(result.current)

    def test_neighbor_parent_mismatch_closes_cross_root_transition(self):
        # 8 is next after 3; checking next's ancestor evidence must not be skipped.
        altered = tuple(
            replace(h, work_title="آخر") if h.source_row_id == 8 else h for h in self.headings
        )
        result = self.trail.navigate(3, SnapshotCatalog(altered))
        self.assertEqual(result.status, "unverified")
        self.assertIsNone(result.next)
        self.assertIsNone(result.current)

    def test_wrong_edition_cannot_use_same_row_identifiers(self):
        trail = ReadingTrail(self.prepared, EDITION_ID + 1)
        result = trail.navigate(40, self.catalog)
        self.assertEqual(result.status, "unverified")
        self.assertIsNone(result.current)
        result = trail.from_reference(synthetic_case(), 1, self.catalog, source_row_id=9)
        self.assertEqual(result.status, "unverified")
        self.assertIsNone(result.research_return_url)

    def test_single_heading_has_no_previous_or_next(self):
        spec = replace(self.prepared.spec, expected_rows=1, expected_roots=1, expected_max_depth=1)
        trail = ReadingTrail(prepare_catalog(spec, self.prepared.records[:1]), EDITION_ID)
        result = trail.navigate(1, SnapshotCatalog(self.headings[:1]))
        self.assertEqual(result.status, "verified")
        self.assertIsNone(result.previous)
        self.assertIsNone(result.next)
        self.assertEqual(len(result.breadcrumbs), 1)

    def test_ambiguous_reference_ordinal_cannot_select_a_return_occurrence(self):
        case = synthetic_case()
        case = replace(case, references=(case.references[0], case.references[0]))
        result = self.trail.from_reference(case, 1, self.catalog)
        self.assertEqual(result.status, "unverified")
        self.assertIsNone(result.research_return_url)

    def test_invalid_topologies_and_bounds_reject_before_catalog_reads(self):
        first, second, *rest = self.prepared.records
        for changes in (
            {"source_order": first.source_order},
            {"source_row_id": first.source_row_id},
            {"source_id": first.source_id},
            {"parent_source_row_id": 999},
            {"parent_source_row_id": second.source_row_id},
            {"depth": 6},
            {"position": True},
            {"title_original": " "},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ReadingTrail(
                    replace(self.prepared, records=(first, replace(second, **changes), *rest)),
                    EDITION_ID,
                )
        oversized = PreparedCatalog(
            replace(self.prepared.spec, expected_rows=20001), (first,) * 20001, "a" * 64
        )
        with self.assertRaises(ValueError):
            ReadingTrail(oversized, EDITION_ID)
