"""Synthetic metadata tests; no scholarly or real-source acceptance claims."""

import json
import unittest
from dataclasses import replace

from apps.reference.records import InvalidCatalog, prepare_catalog
from tests.fiqh_import.test_catalog_audit import synthetic_catalog
from tools.fiqh_import.citation_audit import audit_citation_metadata


class CitationMetadataTests(unittest.TestCase):
    def setUp(self):
        self.prepared, _, _ = synthetic_catalog()

    def test_rerun_preserves_input_and_reports_named_and_lexical_parts(self):
        before = repr(self.prepared)
        first = audit_citation_metadata(self.prepared)
        self.assertEqual(first, audit_citation_metadata(self.prepared))
        self.assertEqual(before, repr(self.prepared))
        observations = first["observations"]
        self.assertEqual(observations["NAMED_PART"]["sample_heading_ids"], [1])
        self.assertEqual(observations["LEXICAL_NUMERIC_PART"]["heading_count"], 6)
        self.assertEqual(observations["ENTRY_NUMBER_ABSENT"]["heading_count"], 1)
        self.assertEqual(first["database_match"], "NOT_ASSERTED_BY_THIS_SUMMARY")

    def test_shared_locators_and_titles_are_bounded_informational_observations(self):
        rows = list(self.prepared.records)
        rows[2] = replace(
            rows[2], source_part=rows[1].source_part,
            source_page_number=rows[1].source_page_number,
            source_page_id=rows[1].source_page_id, title_original=rows[1].title_original,
        )
        prepared = prepare_catalog(self.prepared.spec, rows)
        report = audit_citation_metadata(prepared, max_samples=1)
        for code in ("SHARED_PRINTED_LOCATOR", "SHARED_SOURCE_PAGE_ID", "REPEATED_ORIGINAL_TITLE"):
            self.assertEqual(report["observations"][code], {
                "heading_count": 2, "sample_heading_ids": [2], "samples_omitted": 1,
            })
        self.assertNotIn(rows[1].title_original, json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["observation_semantics"], "INFORMATIONAL_NOT_INTEGRITY_FAILURES")

    def test_same_page_number_in_different_parts_is_distinct(self):
        rows = list(self.prepared.records)
        rows[1] = replace(rows[1], source_page_number=rows[0].source_page_number)
        report = audit_citation_metadata(prepare_catalog(self.prepared.spec, rows))
        self.assertEqual(report["observations"]["SHARED_PRINTED_LOCATOR"]["heading_count"], 0)

    def test_invalid_bounds_and_changed_checksum_fail_closed(self):
        for value in (True, 0, 101, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit_citation_metadata(self.prepared, max_samples=value)
        with self.assertRaises(InvalidCatalog):
            audit_citation_metadata(replace(self.prepared, checksum="0" * 64))
