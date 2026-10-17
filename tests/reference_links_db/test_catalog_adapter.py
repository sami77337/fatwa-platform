"""Real adapter evidence on disposable synthetic PostgreSQL only; no source import."""

import json
from contextlib import contextmanager
from dataclasses import asdict, replace

from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.editorial_demo.integration import compose_synthetic_batch
from apps.fatwa_drafts.intake import ReferenceLink
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.bridge import (
    BridgeConfig, EditionMap, HeadingMap, SourceIdentity, resolve_prepared_pointers,
)
from apps.reference_links.django_adapter import DjangoCatalog
from apps.reference_links.resolution import CatalogReadError, Outcome, SnapshotCatalog, resolve


class CatalogAdapterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        work = ReferenceWork.objects.create(
            source_namespace="e3-synthetic", source_book_id="622",
            title_original='مرجع & <تجريبي> "فقط"', madhhab="synthetic",
        )
        cls.edition = ReferenceEdition.objects.create(
            work=work, edition_key="e3-explicit-edition", title="طبعة اصطناعية",
            publisher="synthetic", source_archive_sha256="a" * 64,
            source_input_sha256="b" * 64, input_name="synthetic.jsonl",
            ingest_checksum="c" * 64, heading_count=5, root_count=1, max_depth=5,
        )
        cls.titles = ("جذرٌ", "كتابٌ", "بابٌ", "فصلٌ", 'عنوان <اصطناعي> & "مشكولٌ"')
        parent = None
        for i, title in enumerate(cls.titles, 1):
            parent = ReferenceHeading.objects.create(
                edition=cls.edition, source_id=f"opaque-{i}", source_row_id=700 + i,
                parent=parent, source_order=i, position=1, depth=i,
                source_page_id=100 + i, source_part="الجزء الأول", source_page_number=20 + i,
                title_original=title, title_normalized="unused-derived",
            )
        cls.target = parent

    def setUp(self):
        self.identity = SourceIdentity("e3-synthetic", "622", "e3-explicit-edition",
                                       "a" * 64, "b" * 64)
        self.config = BridgeConfig(EditionMap(self.identity, self.edition.pk), (
            HeadingMap("text-source", "text-heading", "text-row", self.target.source_row_id),
        ))
        self.pointer = {"source_id": "text-source", "heading_id": "text-heading"}
        self.adapter = DjangoCatalog()

    def bridge(self, pointer=None):
        raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [
            {"external_id": "e3-synthetic-row", "reference_links": [pointer or self.pointer]},
        ]}).encode()
        return resolve_prepared_pointers(raw, self.config, self.adapter)[0].reference_links[0]

    def use_distinct_edition(self, **stored_metadata):
        # Immutable rows are never updated, even in synthetic tests.
        key = self._testMethodName
        fields = {f.attname: getattr(self.edition, f.attname)
                  for f in ReferenceEdition._meta.concrete_fields
                  if f.name not in ("id", "ingested_at")}
        fields.update(edition_key=key)
        fields.update(stored_metadata)
        edition = ReferenceEdition.objects.create(**fields)
        parent = None
        for old in ReferenceHeading.objects.filter(edition=self.edition).order_by("depth"):
            values = {f.attname: getattr(old, f.attname)
                      for f in ReferenceHeading._meta.concrete_fields if f.name != "id"}
            values.update(edition_id=edition.pk, parent_id=parent.pk if parent else None)
            parent = ReferenceHeading.objects.create(**values)
        self.identity = replace(self.identity, edition_key=key)
        self.config = replace(self.config, edition=EditionMap(self.identity, edition.pk))

    @contextmanager
    def select_queries(self):
        with CaptureQueriesContext(connection) as queries:
            yield queries
        self.assertTrue(queries.captured_queries)
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries),
                        [q["sql"] for q in queries])

    def test_correct_deep_path_original_provenance_escaping_and_selects_only(self):
        with self.select_queries() as queries:
            result = self.bridge()
        self.assertEqual(len(queries), 6)  # one edition + target + four parents
        self.assertEqual(result.status, Outcome.VERIFIED)
        self.assertEqual(result.evidence.path, self.titles)
        self.assertEqual(result.evidence.printed_part, "الجزء الأول")
        self.assertEqual(result.evidence.printed_page, 25)
        self.assertEqual(result.evidence.source_input_sha256, "b" * 64)
        self.assertEqual(dict(result.original_pointer), self.pointer)
        self.assertIn("&lt;اصطناعي&gt; &amp; &quot;مشكولٌ&quot;", result.citation)
        self.assertIn("وليس نص فتوى", result.citation)
        self.assertNotIn("<اصطناعي>", result.citation)
        self.assertNotIn("e3-explicit-edition", result.citation)

    def test_c2_all_six_fields_and_full_original_pointer(self):
        pointer = {**asdict(self.identity), "source_id": "text-row"}
        with self.select_queries():
            result = self.bridge(pointer)
        self.assertEqual(result.status, Outcome.VERIFIED)
        self.assertEqual(result.original_pointer, tuple(pointer.items()))
        for key in pointer:
            altered = {**pointer, key: "wrong"}
            with self.assertNumQueries(0):
                bad = self.bridge(altered)
            self.assertEqual(bad.status, Outcome.UNVERIFIED)
            self.assertIsNone(bad.evidence)
            self.assertIsNone(bad.citation)

    def test_missing_edition_and_heading(self):
        with self.select_queries() as queries:
            self.assertEqual(self.adapter.lookup(self.edition.pk, 9999), ())
        self.assertEqual(len(queries), 2)
        with self.select_queries() as queries:
            self.assertEqual(self.adapter.lookup(self.edition.pk + 9999, 705), ())
        self.assertEqual(len(queries), 1)

    def test_opaque_numeric_strings_are_not_cast_by_adapter(self):
        for edition, row in ((str(self.edition.pk), 705), (self.edition.pk, "705"),
                             (True, 705), (self.edition.pk, 0)):
            with self.subTest(edition=edition, row=row), self.assertNumQueries(0):
                with self.assertRaises(CatalogReadError):
                    self.adapter.lookup(edition, row)

    def test_catalog_input_hash_mismatch_suppresses_citation(self):
        self.use_distinct_edition(source_input_sha256="d" * 64)
        result = self.bridge()
        self.assertEqual(result.reasons, ("catalog_source_pin_mismatch",))
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.citation)

    def test_catalog_archive_hash_mismatch_suppresses_citation(self):
        self.use_distinct_edition(source_archive_sha256="d" * 64)
        result = self.bridge()
        self.assertEqual(result.reasons, ("catalog_source_pin_mismatch",))
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.citation)

    def test_catalog_edition_key_mismatch_suppresses_citation(self):
        self.use_distinct_edition(edition_key="another-edition")
        self.assertEqual(self.bridge().reasons, ("catalog_source_pin_mismatch",))

    def test_wrong_numeric_edition_does_not_find_matching_title(self):
        self.config = replace(self.config, edition=EditionMap(self.identity, self.edition.pk + 9999))
        result = self.bridge()
        self.assertEqual(result.status, Outcome.NOT_FOUND)
        self.assertIsNone(result.citation)

    def test_complete_printed_location_is_required(self):
        # DB constraints forbid absent part/page. Metadata assertions still must match exactly.
        for assertion in ({"printed_part": "الثاني"}, {"printed_page": 24}):
            result = resolve({"edition_id": self.edition.pk, "source_row_id": 705, **assertion},
                             self.adapter)
            self.assertEqual(result.outcome, Outcome.MISMATCHED_METADATA)
        fields = {f.attname: getattr(self.target, f.attname)
                  for f in ReferenceHeading._meta.concrete_fields if f.name != "id"}
        fields.update(source_id="incomplete-location", source_row_id=706, source_order=6, position=2)
        for invalid in ({"source_part": ""}, {"source_page_number": 0}):
            with self.subTest(invalid=invalid), transaction.atomic(), self.assertRaises(IntegrityError):
                ReferenceHeading.objects.create(**{**fields, **invalid})

    def test_ambiguity_rejected_by_db_and_by_snapshot_from_real_adapter_evidence(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ReferenceHeading.objects.create(
                edition=self.edition, source_id="duplicate-row", source_row_id=705,
                source_order=6, position=2, depth=1, source_page_id=106,
                source_part="الأول", source_page_number=26,
                title_original="نفس الهوية", title_normalized="unused",
            )
        evidence = self.adapter.lookup(self.edition.pk, 705)[0]
        result = resolve({"edition_id": self.edition.pk, "source_row_id": 705},
                         SnapshotCatalog((evidence, evidence)))
        self.assertEqual(result.outcome, Outcome.AMBIGUOUS)
        self.assertIsNone(result.evidence)

    def test_actual_database_read_failure_is_unverified(self):
        # Temporary DDL only in this test DB; rollback restores the table immediately.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE reference_referenceheading RENAME TO e3_unavailable')
            result = self.bridge()
            self.assertEqual(result.reasons, ("catalog_unavailable",))
            self.assertIsNone(result.citation)
            transaction.set_rollback(True)
        self.assertEqual(self.bridge().status, Outcome.VERIFIED)

    def test_database_rejects_malformed_hierarchy_and_snapshot_mutation(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ReferenceHeading.objects.create(
                edition=self.edition, source_id="invalid-depth-edge", source_row_id=706,
                parent=self.target, source_order=6, position=1, depth=4,
                source_page_id=106, source_part="الأول", source_page_number=26,
                title_original="اصطناعي", title_normalized="unused",
            )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ReferenceHeading.objects.filter(pk=self.target.pk).update(title_original="changed")
        self.assertEqual(self.bridge().status, Outcome.VERIFIED)

    def pipeline(self, catalog=None):
        original = {"external_id": "synthetic-d1-adapter", "question": "  سُؤالٌ\tاصطناعي\n  ",
                    "prepared_clip_url": "https://example.invalid/prepared.mp4",
                    "reference_links": [self.pointer]}
        raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [original]},
                         ensure_ascii=False).encode()
        mapped = self.config.headings[0]
        reference_map = {C1Pointer(**self.pointer): ExplicitMapping(
            ReferenceLink(**asdict(self.identity), source_id=mapped.c2_source_id),
            self.config.edition.edition_id, mapped.source_row_id, "synthetic-db-pin-regression")}
        adapter = catalog if catalog is not None else self.adapter
        with self.select_queries():
            batch = prepare_batch(raw, synthetic_fixtures_only=True,
                                  reference_map=reference_map, catalog=adapter)
            preview = compose_synthetic_batch(raw, synthetic_fixtures_only=True,
                reference_map=reference_map, bridge_config=self.config, catalog=adapter)[0]
            bridge = resolve_prepared_pointers(raw, self.config, adapter)[0].reference_links[0]
        self.assertEqual(batch.report["items"][0]["original"], original)
        self.assertEqual(batch.drafts[0].intake.question, original["question"])
        return batch.report["items"][0], bridge, preview

    def assert_pipeline_pin_mismatch(self):
        row, bridge, preview = self.pipeline()
        self.assertEqual(row["references"][0]["outcome"], "mismatched")
        self.assertEqual(row["references"][0]["reasons"], ["C2_source_identity_mismatch"])
        self.assertIn("references-unverified", row["statuses"])
        self.assertEqual(bridge.reasons, ("catalog_source_pin_mismatch",))
        self.assertIsNone(bridge.citation)
        self.assertEqual(preview.references[0].status, "unverified")
        self.assertIsNone(preview.references[0].citation)
        self.assertEqual(preview.status, "needs-editor-review")

    def test_pipeline_actual_adapter_edition_key_mismatch(self):
        self.use_distinct_edition(edition_key="another-explicit-edition")
        self.assert_pipeline_pin_mismatch()

    def test_pipeline_actual_adapter_archive_hash_mismatch(self):
        self.use_distinct_edition(source_archive_sha256="d" * 64)
        self.assert_pipeline_pin_mismatch()

    def test_pipeline_actual_adapter_matching_metadata(self):
        row, bridge, preview = self.pipeline()
        self.assertEqual(row["references"][0]["outcome"], "verified")
        self.assertNotIn("references-unverified", row["statuses"])
        self.assertEqual(bridge.status, Outcome.VERIFIED)
        self.assertEqual(preview.references[0].status, "verified")
        self.assertIsNotNone(preview.references[0].citation)

    def test_pipeline_actual_adapter_legacy_optional_metadata_projection(self):
        adapter = self.adapter

        class LegacyCatalog:
            def lookup(self, edition_id, source_row_id):
                return tuple(replace(heading, edition_key=None, source_archive_sha256=None)
                             for heading in adapter.lookup(edition_id, source_row_id))

        row, bridge, preview = self.pipeline(LegacyCatalog())
        self.assertEqual(row["references"][0]["outcome"], "verified")
        self.assertEqual(bridge.status, Outcome.VERIFIED)
        self.assertEqual(preview.references[0].status, "verified")
