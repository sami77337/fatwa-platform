"""Cross-lane compatibility on the original synthetic services, without persistence."""

import json
from dataclasses import asdict
from hashlib import sha256

from django.test import SimpleTestCase

from apps.arabic_text_quality.service import inspect_revision, inspect_text
from apps.editorial_duplicate_candidates.services import build_duplicate_report
from apps.editorial_export.comparison import compare_exports
from apps.editorial_export.services import build_export
from apps.editorial_queue.services import build_queue_catalog, select_queue
from apps.editorial_search.services import search_catalog
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference_links.resolution import SnapshotCatalog
from apps.revision_lineage_inspector import inspect_lineage
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture
from tools.revision_lineage_inspector.fixtures import synthetic_fixture as lineage_fixture


class Fast7BCCompatibilityTests(SimpleTestCase):
    def test_review_search_duplicates_and_export_retain_the_same_exact_case_identity(self):
        catalog = build_queue_catalog()
        original = asdict(catalog)
        bundle = build_export(synthetic_fixtures_only=True)
        packets = {
            item["packet"]["identity"]["case_key"]: item["packet"]
            for item in bundle.report()["cases"]
        }
        duplicates = build_duplicate_report(synthetic_fixtures_only=True)
        compared = {item.source.case_key: item for item in duplicates.cases}
        self.assertEqual(len(catalog.rows), 20)
        self.assertEqual(set(compared), set(packets))
        for status, expected in (
            ("review-with-draft", ("history", "batch-synthetic-json-2")),
            ("review-without-draft", ("intake-2", "batch-synthetic-csv-3")),
        ):
            rows = select_queue(catalog.rows, status=status).rows
            self.assertEqual(tuple(row.case.key for row in rows), expected)
            for row in rows:
                with self.subTest(key=row.case.key):
                    hit = search_catalog(catalog, q=row.case.key, source="record").hits[0]
                    self.assertEqual(hit.case_key, row.case.key)
                    self.assertEqual(hit.source_sha256, row.source_sha256)
                    self.assertEqual(compared[row.case.key].source.batch_id, row.batch_id)
                    self.assertEqual(compared[row.case.key].source.source_sha256, hit.source_sha256)
                    packet = packets[row.case.key]
                    self.assertEqual(packet["source"]["text_sha256"], hit.source_sha256)
                    self.assertEqual(packet["identity"]["external_id"], row.case.external_id)
                    quality = inspect_text(row.case.question, synthetic_only=True)
                    self.assertEqual(quality.sources[0].text, compared[row.case.key].text)
                    self.assertEqual(quality.sources[0].sha256, compared[row.case.key].text_sha256)
        comparison = json.loads(
            compare_exports(
                dict(bundle.files),
                dict(build_export(synthetic_fixtures_only=True).files),
                synthetic_fixtures_only=True,
            )
        )
        self.assertTrue(comparison["identical"])
        self.assertEqual(asdict(catalog), original)

    def test_quality_inspection_preserves_lineage_and_missing_evidence(self):
        fixture = lineage_fixture()
        original = asdict(fixture)
        arguments = dict(
            expected_case_id=fixture.expected_case_id,
            workflow=fixture.workflow,
            expected_row_id=fixture.expected_row_id,
            expected_batch_id=fixture.expected_batch_id,
            source_payload=fixture.source_payload,
            synthetic_fixtures_only=True,
        )
        before = inspect_lineage(fixture.record, **arguments)
        report = inspect_revision(
            fixture.record.current,
            previous=fixture.record.history[0],
            synthetic_only=True,
        )
        self.assertEqual(report.mode, "comparison")
        answer = next(source for source in report.sources if source.side == "after.answer")
        self.assertEqual(answer.text, fixture.record.current.answer)
        self.assertEqual(answer.sha256, sha256(answer.text.encode("utf-8")).hexdigest())
        after = inspect_lineage(fixture.record, **arguments)
        self.assertEqual(after, before)
        self.assertEqual(after.status, "CONSISTENT_WITH_LIMITATIONS")
        checks = {check.code: check.status for check in after.checks}
        self.assertEqual(checks["snapshot_event_relationship"], "UNAVAILABLE")
        self.assertEqual(checks["draft_workflow_binding"], "UNAVAILABLE")
        self.assertEqual(asdict(fixture), original)

    def test_reading_trail_and_quality_keep_source_pins_and_exact_research_return(self):
        prepared, headings = synthetic_fixture()
        original = (asdict(prepared), tuple(asdict(heading) for heading in headings))
        trail = ReadingTrail(prepared, EDITION_ID)
        catalog = SnapshotCatalog(headings)
        case = synthetic_case()
        first = trail.from_reference(case, 1, catalog)
        self.assertEqual(first.status, "verified")
        continued = trail.from_reference(case, 1, catalog, source_row_id=42)
        self.assertEqual(continued.status, "verified")
        self.assertEqual(continued.research_return_url, "/dev/research-bridge/intake-1#reference-1")
        self.assertEqual(continued.current.catalog_url, "/fiqh/nodes/42?edition=7001")
        self.assertEqual(
            [item.evidence.source_row_id for item in continued.breadcrumbs], [1, 2, 40, 41, 42]
        )
        for item in continued.breadcrumbs:
            quality = inspect_text(item.evidence.heading_title, synthetic_only=True)
            self.assertEqual(quality.sources[0].text, item.evidence.heading_title)
            self.assertEqual(item.evidence.source_input_sha256, "b" * 64)
            self.assertEqual(item.evidence.source_archive_sha256, "a" * 64)
        self.assertEqual(
            (asdict(prepared), tuple(asdict(heading) for heading in headings)), original
        )
