"""Real fixture semantics, stable identities, and non-mutating selection."""

from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_followup import services
from apps.editorial_queue.services import build_queue_catalog


class FollowupServicesTests(SimpleTestCase):
    def setUp(self):
        self.source = build_queue_catalog()
        self.catalog = services.build_followup()
        self.by_key = {item.row.case.key: item for item in self.catalog.rows}

    def codes(self, key):
        return {reason.code for reason in self.by_key[key].reasons}

    def test_reuses_all_fixed_identities_without_altering_text_or_provenance(self):
        self.assertEqual(len(self.catalog.rows), 20)
        self.assertEqual(self.catalog.batches, self.source.batches)
        self.assertEqual(tuple(item.row for item in self.catalog.rows), self.source.rows)
        self.assertEqual(self.catalog, services.build_followup())
        for item in self.catalog.rows:
            self.assertEqual(
                item.row.source_sha256, sha256(item.row.case.raw_source.encode()).hexdigest()
            )
        with patch.object(services, "build_queue_catalog", return_value=self.source) as build:
            services.build_followup()
        build.assert_called_once_with()

    def test_status_is_independent_of_reference_and_receipt_facts(self):
        self.assertEqual(self.codes("batch-synthetic-jsonl-1"), {"missing_references"})
        self.assertEqual(self.codes("batch-synthetic-json-2"), {"unresolved_references"})
        self.assertEqual(self.codes("history"), {"unresolved_references"})
        self.assertEqual(
            self.codes("batch-synthetic-csv-3"), {"input_correction", "missing_receipt"}
        )
        self.assertEqual(self.codes("intake-7"), set())

    def test_rejected_duplicate_ids_keep_distinct_rows_without_borrowed_receipts(self):
        for key in ("batch-synthetic-csv-2", "batch-synthetic-json-1"):
            self.assertTrue(
                {"rejected_row", "missing_receipt", "input_correction"} <= self.codes(key)
            )
            item = self.by_key[key]
            self.assertIsNone(item.row.case.record)
            self.assertEqual(item.preparation[0].code, "duplicate_id")
            self.assertIn("الأصل", item.preparation[0].guidance)

    def test_real_counts_and_malformed_batch_do_not_invent_rows(self):
        expected = {
            "missing_receipt": 14,
            "rejected_row": 12,
            "missing_references": 8,
            "unresolved_references": 4,
        }
        for code, count in expected.items():
            self.assertEqual(
                len(services.select_followup(self.catalog.rows, reason=code).rows), count
            )
        self.assertEqual(len(services.select_followup(self.catalog.rows).rows), 17)
        self.assertEqual(
            services.select_followup(self.catalog.rows, batch="synthetic-malformed").rows, ()
        )
        self.assertEqual(self.catalog.batches[-1].source.error_code, "MALFORMED_INPUT")

    def test_ambiguous_unresolved_and_conflicting_references_keep_exact_ordinals(self):
        original = next(row for row in self.source.rows if row.case.key == "intake-7")
        for status in (
            "ambiguous",
            "not_found",
            "unverified",
            "unresolved",
            "mismatched",
            "mismatched_metadata",
        ):
            refs = tuple(
                {**original.case.references[0], "status": status, "reference_ordinal": i}
                for i in (1, 2)
            )
            changed = replace(original, case=replace(original.case, references=refs))
            with patch.object(
                services, "build_queue_catalog", return_value=replace(self.source, rows=(changed,))
            ):
                item = services.build_followup().rows[0]
            self.assertEqual({reason.code for reason in item.reasons}, {"unresolved_references"})
            self.assertEqual(item.references, refs)

    def test_navigation_is_stable_filtered_and_does_not_wrap(self):
        rows = self.catalog.rows
        matches = services.select_followup(rows, reason="missing_receipt", status="blocked").rows
        for i, item in enumerate(matches):
            selection = services.select_followup(
                rows, reason="missing_receipt", status="blocked", key=item.row.case.key
            )
            self.assertIs(selection.selected, item)
            self.assertEqual(selection.position, i + 1)
            self.assertIs(selection.previous, matches[i - 1] if i else None)
            self.assertIs(selection.next, matches[i + 1] if i + 1 < len(matches) else None)
        outside = services.select_followup(rows, reason="missing_receipt", key="history")
        self.assertIs(outside.selected, self.by_key["history"])
        self.assertEqual((outside.position, outside.previous, outside.next), (None, None, None))
        self.assertIsNone(services.select_followup(rows, key="unknown").selected)

    def test_no_reason_direct_detail_is_inspectable_without_claiming_approval(self):
        selection = services.select_followup(self.catalog.rows, key="intake-7")
        self.assertEqual(selection.selected.reasons, ())
        self.assertIsNone(selection.position)

    def test_combined_filters_and_empty_matches(self):
        selection = services.select_followup(
            self.catalog.rows, reason="missing_receipt", batch="synthetic-csv", status="review"
        )
        self.assertEqual([item.row.case.key for item in selection.rows], ["batch-synthetic-csv-3"])
        self.assertEqual(
            services.select_followup(
                self.catalog.rows, reason="missing_receipt", status="ready"
            ).rows,
            (),
        )
