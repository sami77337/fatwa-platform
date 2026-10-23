"""Adversarial reports over fabricated evidence; no owner source or database."""

import hashlib
import json
import unicodedata
import unittest
from dataclasses import replace
from unittest.mock import patch

from apps.intake_workflow import contracts as c, fixtures
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading


ROOT = Heading(
    7001, 1, "مرجع اصطناعي لتجارب Wave7", "كِتَابٌ اصطناعي", "الأول", 7,
    ("كِتَابٌ اصطناعي",), "wave7-synthetic-toc", "622", "b" * 64,
    "wave7-synthetic-edition-v1", "a" * 64,
)
C1 = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}
C2 = {**c.SOURCE_IDENTITY, "source_id": "wave7-title-1"}


def payload(items):
    return json.dumps(
        {"schema": c.PAYLOAD_SCHEMA, "synthetic_fixtures_only": True, "items": items},
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


class DiagnosticAdversarialTests(unittest.TestCase):
    def report(self, items, rows=(ROOT,)):
        return build_reference_diagnostics(
            payload(items), synthetic_fixtures_only=True, catalog_rows=rows,
        ).to_payload()

    def assert_unresolved(self, reference, reason, status="unresolved"):
        self.assertEqual(reference["status"], status)
        self.assertEqual(reference["reasons"], [reason])
        self.assertEqual(reference["verified_identity"], {})
        self.assertIsNone(reference["evidence"])

    def test_same_row_in_other_edition_cannot_shadow_the_exact_source(self):
        other = replace(
            ROOT, edition_id=7002, source_namespace="other-synthetic-toc",
            source_book_id="623", edition_key="other-edition",
            source_archive_sha256="c" * 64, source_input_sha256="d" * 64,
        )
        for rows in ((other, ROOT), (ROOT, other)):
            with self.subTest(first_edition=rows[0].edition_id):
                output = self.report([{"reference_links": [C1, C2]}], rows)
                refs = output["items"][0]["references"]
                self.assertEqual(output["summary"],
                                 {"verified": 2, "unresolved": 0, "mismatched": 0})
                for ref in refs:
                    self.assertEqual(ref["verified_identity"], dict(c.VERIFIED_IDENTITIES[0]))
                    self.assertEqual(ref["evidence"]["edition_id"], 7001)
                    self.assertEqual(ref["evidence"]["source_input_sha256"], "b" * 64)
                self.assertEqual([row["edition_id"] for row in output["asserted_catalog"]],
                                 [row.edition_id for row in rows])

    def test_colliding_pins_cannot_be_filtered_into_a_preferred_candidate(self):
        changes = (
            ("source_namespace", "other-synthetic-toc"), ("source_book_id", "623"),
            ("edition_key", "other-edition"), ("source_archive_sha256", "c" * 64),
            ("source_input_sha256", "d" * 64),
        )
        for field, value in changes:
            conflict = replace(ROOT, **{field: value})
            # The snapshot may cap lookup candidates at two, but diagnostics
            # must preserve all three asserted rows, including identical rows.
            for rows in ((ROOT, conflict, ROOT), (conflict, ROOT, ROOT),
                         (ROOT, ROOT, conflict)):
                with self.subTest(field=field, values=[getattr(row, field) for row in rows]):
                    output = self.report([{"reference_links": [C1, C2]}], rows)
                    for ref in output["items"][0]["references"]:
                        self.assert_unresolved(ref, "multiple_exact_candidates")
                    self.assertEqual(output["summary"],
                                     {"verified": 0, "unresolved": 2, "mismatched": 0})
                    self.assertEqual([row[field] for row in output["asserted_catalog"]],
                                     [getattr(row, field) for row in rows])

    def test_duplicate_detection_is_per_item_and_does_not_merge_pointer_formats(self):
        items = [{"reference_links": [C1, C2, dict(reversed(list(C1.items())))]},
                 {"reference_links": [C1, C2]}]
        output = self.report(items)
        first, second = [item["references"] for item in output["items"]]
        self.assertEqual([ref["reference_ordinal"] for ref in first], [1, 2, 3])
        self.assert_unresolved(first[0], "duplicate_pointer")
        self.assert_unresolved(first[2], "duplicate_pointer")
        for ref in (first[1], *second):
            self.assertEqual(ref["status"], "verified")
            self.assertEqual(ref["reasons"], [])
            self.assertEqual(ref["verified_identity"], dict(c.VERIFIED_IDENTITIES[0]))
        self.assertEqual([ref["reference_ordinal"] for ref in second], [1, 2])
        self.assertEqual(output["summary"], {"verified": 3, "unresolved": 2, "mismatched": 0})

    def test_each_missing_c2_identity_field_keeps_the_original_incomplete_pointer(self):
        pointers = [{key: value for key, value in C2.items() if key != missing} for missing in C2]
        output = self.report([{"reference_links": pointers}])
        refs = output["items"][0]["references"]
        self.assertEqual(len(refs), 6)
        for number, (pointer, ref) in enumerate(zip(pointers, refs, strict=True), 1):
            self.assertEqual(ref["reference_ordinal"], number)
            self.assert_unresolved(ref, "unsupported_pointer_shape")
            self.assertEqual(json.loads(ref["source"]["text"]), pointer)

    def test_one_absent_legacy_pin_never_masks_a_conflicting_present_pin(self):
        for changes in ({"edition_key": None, "source_archive_sha256": "c" * 64},
                        {"edition_key": "other-edition", "source_archive_sha256": None}):
            with self.subTest(changes=changes):
                output = self.report([{"reference_links": [C1, C2]}],
                                     (replace(ROOT, **changes),))
                for ref in output["items"][0]["references"]:
                    self.assert_unresolved(ref, "catalog_metadata_mismatch", "mismatched")
                for field, value in changes.items():
                    self.assertEqual(output["asserted_catalog"][0][field], value)

    def test_each_legacy_pin_requires_complete_configuration_even_for_another_row(self):
        full_config = fixtures.trusted_bridge_config()
        partial_config = replace(full_config, headings=full_config.headings[:2])
        partial_map = {
            pointer: mapping for pointer, mapping in fixtures.trusted_reference_map().items()
            if mapping.source_row_id != 3
        }
        replacements = (("trusted_bridge_config", partial_config),
                        ("trusted_reference_map", partial_map))
        for function, configuration in replacements:
            for field in ("edition_key", "source_archive_sha256"):
                with self.subTest(configuration=function, absent=field):
                    with patch.object(fixtures, function, return_value=configuration):
                        legacy = self.report([{"reference_links": [C1]}],
                                             (replace(ROOT, **{field: None}),))
                        complete = self.report([{"reference_links": [C1]}])
                    self.assert_unresolved(legacy["items"][0]["references"][0],
                                           "trusted_configuration_incomplete")
                    self.assertIsNone(legacy["asserted_catalog"][0][field])
                    self.assertEqual(complete["items"][0]["references"][0]["status"], "verified")

    def test_absent_reference_lists_preserve_row_gaps_without_inferred_references(self):
        items = [None, {"question": "كِتَابٌ اصطناعي"}, {"reference_links": None},
                 {"reference_links": C1}, {"reference_links": [C1]}]
        raw = payload(items)
        output = self.report(items)
        self.assertEqual([item["row_ordinal"] for item in output["items"]], [1, 2, 3, 4, 5])
        self.assertEqual([len(item["references"]) for item in output["items"]], [0, 0, 0, 0, 1])
        last = output["items"][4]["references"][0]
        self.assertEqual(last["reference_ordinal"], 1)
        self.assertEqual(last["status"], "verified")
        for item, expected in zip(output["items"], items, strict=True):
            source = item["source"]
            self.assertEqual(raw[source["start"]:source["end"]], source["text"].encode("utf-8"))
            self.assertEqual(json.loads(source["text"]), expected)

    def test_canonically_equivalent_heading_text_is_still_a_metadata_mismatch(self):
        title = "بابٌ اصطناعي أول"
        decomposed = unicodedata.normalize("NFD", title)
        self.assertNotEqual(title, decomposed)
        row = replace(ROOT, source_row_id=2, heading_title=decomposed, printed_page=8,
                      path=(ROOT.heading_title, decomposed))
        pointer = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-2"}
        output = self.report([{"reference_links": [pointer]}], (row,))
        self.assert_unresolved(output["items"][0]["references"][0],
                               "catalog_metadata_mismatch", "mismatched")
        self.assertEqual(output["asserted_catalog"][0]["heading_title"], decomposed)
        self.assertEqual(output["asserted_catalog"][0]["path"], [ROOT.heading_title, decomposed])

    def test_unicode_byte_offsets_and_hashes_preserve_escapes_and_distinct_normalizations(self):
        tokens = [
            b'{ "source_id":"\\u00577-SOURCE","heading_id":"W7-HEADING-1" }',
            '{"source_id":"أ"}'.encode("utf-8"),
            '{"source_id":"أ"}'.encode("utf-8"),
        ]
        prefix = ('{"schema":"' + c.PAYLOAD_SCHEMA + '","synthetic_fixtures_only":true,'
                  '"items":[null,{"question":"سُؤال 🧪 \\" } ] \\" ‏",'
                  '"reference_links":[').encode("utf-8")
        raw = prefix + b",".join(tokens) + b"]}]}"
        report = build_reference_diagnostics(raw, synthetic_fixtures_only=True, catalog_rows=(ROOT,))
        output = report.to_payload()
        refs = output["items"][1]["references"]
        self.assertEqual([item["row_ordinal"] for item in output["items"]], [1, 2])
        self.assertEqual([ref["reference_ordinal"] for ref in refs], [1, 2, 3])
        self.assertEqual(refs[0]["status"], "verified")
        self.assert_unresolved(refs[1], "unsupported_pointer_shape")
        self.assert_unresolved(refs[2], "unsupported_pointer_shape")
        self.assertEqual(output["input_sha256"], hashlib.sha256(raw).hexdigest())
        for ref, token in zip(refs, tokens, strict=True):
            expected_start = raw.index(token)
            self.assertEqual(ref["source"]["start"], expected_start)
            self.assertEqual(ref["source"]["end"], expected_start + len(token))
            self.assertEqual(ref["source"]["text"].encode("utf-8"), token)
            self.assertEqual(ref["source_sha256"], hashlib.sha256(token).hexdigest())
        self.assertNotEqual(refs[1]["source_sha256"], refs[2]["source_sha256"])
        self.assertEqual(json.loads(report.json_bytes()), output)
