"""Synthetic-only reference-link tests. No database, network, or owner dataset."""

import json
import unittest
from dataclasses import replace

from apps.reference_links import (
    CatalogReadError,
    Heading,
    Outcome,
    SnapshotCatalog,
    render_citation,
    resolve,
    resolve_intake,
)

BASE = Heading(
    edition_id=1,
    source_row_id=7,
    work_title="كتاب تجريبي & <مرجع>",
    heading_title="باب ماءٍ",
    printed_part="الأول",
    printed_page=12,
    path=("جذر", "كتاب", "فصل", "قسم", "باب ماءٍ"),
    source_namespace="synthetic",
    source_book_id="synthetic-1",
    source_input_sha256="a" * 64,
)


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = SnapshotCatalog((BASE, replace(BASE, edition_id=2, printed_page=99)))
        self.link = {"edition_id": 1, "source_row_id": 7}

    def test_verified_deep_path_and_provenance(self):
        result = resolve(self.link, self.catalog)
        self.assertEqual(result.outcome, Outcome.VERIFIED)
        payload = result.internal_payload()
        self.assertEqual(payload["provenance"]["path"], BASE.path)
        self.assertEqual(payload["provenance"]["source_input_sha256"], "a" * 64)
        self.assertEqual(payload["toc_url"], "/fiqh/nodes/7?edition=1")

    def test_cross_edition_isolation(self):
        self.assertEqual(
            resolve({**self.link, "edition_id": 2}, self.catalog).evidence.printed_page, 99
        )
        self.assertEqual(
            resolve({**self.link, "edition_id": 3}, self.catalog).outcome, Outcome.NOT_FOUND
        )
        self.assertEqual(resolve({"source_row_id": 7}, self.catalog).outcome, Outcome.UNVERIFIED)

    def test_duplicate_identity_ambiguous_even_if_metadata_matches(self):
        catalog = SnapshotCatalog((BASE, replace(BASE, printed_page=14)))
        self.assertEqual(
            resolve({**self.link, "printed_page": 12}, catalog).outcome, Outcome.AMBIGUOUS
        )

    def test_changed_names_and_locations(self):
        for key, value in (
            ("work_title", "آخر"),
            ("heading_title", "باب ماء"),
            ("printed_part", "الثاني"),
            ("printed_page", 13),
        ):
            with self.subTest(key=key):
                result = resolve({**self.link, key: value}, self.catalog)
                self.assertEqual(result.outcome, Outcome.MISMATCHED_METADATA)
                self.assertEqual(result.reasons, (key,))
                self.assertIsNone(result.evidence)

    def test_strict_null_and_types(self):
        for key in (
            "edition_id",
            "source_row_id",
            "work_title",
            "heading_title",
            "printed_part",
            "printed_page",
            "public_node_id",
        ):
            for value in (None, True, "", 0, [], {}):
                with self.subTest(key=key, value=value):
                    self.assertEqual(
                        resolve({**self.link, key: value}, self.catalog).outcome, Outcome.UNVERIFIED
                    )

    def test_missing_source_page_or_part(self):
        for row in (replace(BASE, printed_page=None), replace(BASE, printed_part=None)):
            result = resolve(self.link, SnapshotCatalog((row,)))
            self.assertEqual(result.outcome, Outcome.UNVERIFIED)
            with self.assertRaises(ValueError):
                render_citation(result)

    def test_alias_exact_id(self):
        self.assertEqual(
            resolve({"edition_id": 1, "public_node_id": 7}, self.catalog).outcome, Outcome.VERIFIED
        )
        self.assertEqual(
            resolve({**self.link, "public_node_id": 8}, self.catalog).outcome, Outcome.UNVERIFIED
        )

    def test_no_text_association_or_unknown_fields(self):
        self.assertEqual(
            resolve({"question": BASE.heading_title}, self.catalog).outcome, Outcome.UNVERIFIED
        )

    def test_html_unicode_and_determinism(self):
        row = replace(
            BASE, heading_title='<script>"عَلَم"</script>', path=("جذر", '<script>"عَلَم"</script>')
        )
        result = resolve(self.link, SnapshotCatalog((row,)))
        citation = render_citation(result)
        self.assertEqual(citation, render_citation(result))
        self.assertIn("عَلَم", citation)
        self.assertIn("&lt;script&gt;&quot;", citation)
        self.assertIn("&amp;", citation)
        self.assertNotIn("<script>", citation)
        self.assertNotIn("edition_id", citation)
        self.assertNotIn("synthetic", citation)
        self.assertIn("ص 12", citation)

    def test_invalid_source_evidence(self):
        for row in (
            replace(BASE, path=()),
            replace(BASE, path=("wrong",)),
            replace(BASE, source_input_sha256=""),
            replace(BASE, heading_title="\ud800"),
        ):
            self.assertEqual(
                resolve(self.link, SnapshotCatalog((row,))).outcome, Outcome.UNVERIFIED
            )

    def test_unavailable_and_adapter_identity_violation(self):
        class Unavailable:
            def lookup(self, edition_id, source_row_id):
                raise CatalogReadError()

        class WrongEdition:
            def lookup(self, edition_id, source_row_id):
                return (replace(BASE, edition_id=2),)

        for adapter in (Unavailable(), WrongEdition()):
            self.assertEqual(resolve(self.link, adapter).outcome, Outcome.UNVERIFIED)

    def test_snapshot_bound(self):
        with self.assertRaises(ValueError):
            SnapshotCatalog((BASE,) * 20001)

    def test_intake_no_inference_or_media_access(self):
        raw = json.dumps(
            {
                "schema": "fatwa.prepared-intake.v1",
                "items": [
                    {
                        "external_id": "STAFF-001",
                        "question": BASE.heading_title,
                        "prepared_clip_url": "https://example.invalid/finished.mp4",
                        "staff_notes": "",
                        "reference_links": [self.link],
                    },
                    {"external_id": "STAFF-002", "question": BASE.heading_title},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        results = resolve_intake(raw, self.catalog)
        self.assertEqual(results[0]["reference_links"][0].outcome, Outcome.VERIFIED)
        self.assertEqual(results[1]["reference_links"], [])

    def test_intake_malformed_utf8_duplicates_and_null(self):
        for raw in (
            b"\xff",
            b'{"schema":"x","schema":"y"}',
            b"[]",
            b'{"schema":"fatwa.prepared-intake.v1","items":null}',
            b'{"schema":"fatwa.prepared-intake.v1","items":[{"external_id":"x","reference_links":null}]}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                resolve_intake(raw, self.catalog)


if __name__ == "__main__":
    unittest.main()
