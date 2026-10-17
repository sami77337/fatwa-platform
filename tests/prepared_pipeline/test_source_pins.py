"""D1 compares optional explicit source pins without inferring absent metadata."""
from dataclasses import replace
import json
import unittest

from apps.fatwa_drafts.intake import ReferenceLink
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.reference_links.resolution import Heading, SnapshotCatalog


class SourcePinIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original = {"external_id": "synthetic-pin", "question": "  سُؤالٌ\tاصطناعي\n  ",
                         "prepared_clip_url": "https://example.invalid/prepared.mp4",
                         "reference_links": [{"source_id": "opaque", "heading_id": "heading"}]}
        self.raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [self.original]},
                              ensure_ascii=False).encode()
        self.reference = ReferenceLink("synthetic", "book", "edition", "a" * 64, "b" * 64, "row")
        self.mapping = {C1Pointer("opaque", "heading"): ExplicitMapping(self.reference, 7, 9, "synthetic")}
        self.heading = Heading(7, 9, "مرجع اصطناعي", "عنوانٌ", "الأول", 2, ("عنوانٌ",),
                               "synthetic", "book", "b" * 64, "edition", "a" * 64)

    def prepare(self, **metadata):
        batch = prepare_batch(self.raw, synthetic_fixtures_only=True, reference_map=self.mapping,
                              catalog=SnapshotCatalog((replace(self.heading, **metadata),)))
        self.assertEqual(batch.report["items"][0]["original"], self.original)
        self.assertEqual(batch.drafts[0].intake.question, self.original["question"])
        return batch.report["items"][0]

    def assert_mismatched(self, **metadata):
        row = self.prepare(**metadata)
        self.assertEqual(row["references"][0]["outcome"], "mismatched")
        self.assertEqual(row["references"][0]["reasons"], ["C2_source_identity_mismatch"])
        self.assertIn("references-unverified", row["statuses"])

    def test_explicit_edition_key_mismatch_is_not_verified(self):
        self.assert_mismatched(edition_key="other-edition")

    def test_explicit_archive_hash_mismatch_is_not_verified(self):
        self.assert_mismatched(source_archive_sha256="c" * 64)

    def test_matching_explicit_metadata_is_verified(self):
        row = self.prepare()
        self.assertEqual(row["references"][0]["outcome"], "verified")
        self.assertNotIn("references-unverified", row["statuses"])

    def test_genuinely_absent_optional_metadata_preserves_legacy_snapshots(self):
        for metadata in ({"edition_key": None}, {"source_archive_sha256": None},
                         {"edition_key": None, "source_archive_sha256": None}):
            with self.subTest(metadata=metadata):
                self.assertEqual(self.prepare(**metadata)["references"][0]["outcome"], "verified")
