"""Exercise the real fixed read service and queue identity/navigation adapters."""

from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.editorial_queue import services
from apps.editorial_workbench.services import WorkbenchDataError
from apps.fatwa_drafts.intake import serialize_intake
from apps.intake_workflow import fixtures


class QueueServicesTests(SimpleTestCase):
    def test_fixed_manifest_retains_every_row_even_duplicate_invalid_and_null_ids(self):
        rows = services.build_queue()
        self.assertEqual(
            [row.case.key for row in rows],
            ["history", *[f"intake-{number}" for number in range(1, 9)]],
        )
        self.assertEqual(rows, services.build_queue())
        self.assertEqual(rows[1].case.external_id, rows[4].case.external_id)
        self.assertNotEqual(rows[1].case.question, rows[4].case.question)
        self.assertEqual(rows[5].case.external_id, "BAD\tID")
        self.assertIsNone(rows[-1].case.question)
        self.assertIsNone(rows[-1].case.external_id)
        self.assertEqual(rows[-1].case.raw_source, "null")

    def test_source_bytes_offsets_and_both_hashes_equal_original_fixed_payload(self):
        raw = fixtures.synthetic_payload()
        self.assertEqual(
            sha256(raw).hexdigest(),
            "cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb",
        )
        for row in services.build_queue()[1:]:
            case = row.case
            original_slice = raw[case.source_start : case.source_end]
            self.assertEqual(case.raw_source.encode("utf-8"), original_slice)
            self.assertEqual(case.payload_sha256, sha256(raw).hexdigest())
            self.assertEqual(row.source_sha256, sha256(original_slice).hexdigest())
        self.assertEqual(services.build_queue()[1].case.question, fixtures.ORIGINAL_QUESTION)

    def test_history_reuses_exact_record_and_nonconsecutive_revision_objects(self):
        row = services.build_queue()[0]
        self.assertIs(row.case.record, REVISION_HISTORY_RECORD)
        self.assertEqual([entry.revision.number for entry in row.history], [1, 2, 4, 7, 9, 11])
        for entry in row.history:
            self.assertIs(
                entry.revision,
                next(
                    r for r in REVISION_HISTORY_RECORD.history if r.number == entry.revision.number
                ),
            )
        serialized = serialize_intake((REVISION_HISTORY_RECORD.intake,))
        self.assertEqual(row.case.raw_source.encode("utf-8"), serialized)
        self.assertEqual(row.source_sha256, sha256(serialized).hexdigest())
        self.assertEqual(row.case.payload_sha256, sha256(serialized).hexdigest())
        self.assertIsNone(row.case.source_start)
        self.assertIsNone(row.case.source_end)
        self.assertIn("تسلسل", row.case.fixture_label)

    def test_reference_indicators_distinguish_missing_verified_and_unresolved(self):
        rows = services.build_queue()
        self.assertEqual(rows[0].reference_status, "unresolved")
        self.assertGreater(rows[0].unresolved_count, 0)
        self.assertEqual(rows[1].reference_status, "verified")
        self.assertEqual(rows[1].verified_count, 1)
        self.assertEqual(rows[1].unresolved_count, 0)
        self.assertEqual(rows[1].case.status, "blocked")
        self.assertEqual(rows[2].reference_status, "missing")
        self.assertEqual(rows[2].verified_count, 0)
        self.assertEqual(rows[2].unresolved_count, 0)
        case = replace(
            rows[0].case, references=({"status": "mismatched"}, {"status": "unresolved"})
        )
        with patch.object(services, "build_cases", return_value=(case,)):
            row = services.build_queue()[0]
        self.assertEqual(row.unresolved_count, 2)
        self.assertEqual(row.reference_status, "unresolved")

    def test_missing_drafts_never_borrow_history(self):
        rows = services.build_queue()
        self.assertEqual([row.case.key for row in rows if row.history], ["history", "intake-7"])
        for row in rows:
            if row.case.record is None:
                self.assertEqual(row.history, ())

    def test_filters_keep_manifest_order_and_combine_status_reference_and_search(self):
        rows = services.build_queue()
        for status, _ in services.STATUSES:
            selected = services.select_queue(rows, status=status)
            self.assertTrue(selected.rows)
            self.assertEqual(selected.rows, tuple(row for row in rows if row.case.status == status))
        for refs, _ in services.REFERENCE_FILTERS:
            selected = services.select_queue(rows, refs=refs)
            self.assertTrue(selected.rows)
            self.assertEqual(
                selected.rows, tuple(row for row in rows if row.reference_status == refs)
            )
        selected = services.select_queue(rows, q=" w7-ready-2 ", status="ready", refs="verified")
        self.assertEqual([row.case.key for row in selected.rows], ["intake-7"])
        self.assertEqual(services.select_queue(rows, q="intake-8").rows, (rows[-1],))
        self.assertIn(rows[2], services.select_queue(rows, q="بلا مقطع").rows)
        self.assertEqual(services.select_queue(rows, q="not-in-fixed-fixtures").rows, ())

    def test_every_filtered_record_has_immediate_neighbors_without_wrap(self):
        rows = services.build_queue()
        for filters in ({}, {"status": "blocked"}, {"refs": "missing"}, {"status": "ready"}):
            matches = services.select_queue(rows, **filters).rows
            for index, row in enumerate(matches):
                selected = services.select_queue(rows, key=row.case.key, **filters)
                self.assertIs(selected.selected, row)
                self.assertEqual(selected.position, index + 1)
                self.assertIs(selected.previous, matches[index - 1] if index else None)
                self.assertIs(
                    selected.next, matches[index + 1] if index + 1 < len(matches) else None
                )

    def test_outside_filter_unknown_and_empty_selection_never_infer_neighbors(self):
        rows = services.build_queue()
        outside = services.select_queue(rows, key="history", status="blocked")
        self.assertIs(outside.selected, rows[0])
        self.assertIsNone(outside.position)
        self.assertIsNone(outside.previous)
        self.assertIsNone(outside.next)
        for selected in (
            services.select_queue(rows, key="missing"),
            services.select_queue((), key="history"),
            services.select_queue(rows),
        ):
            self.assertIsNone(selected.selected)
            self.assertIsNone(selected.position)
            self.assertIsNone(selected.previous)
            self.assertIsNone(selected.next)

    def test_duplicate_case_identity_is_rejected(self):
        case = services.build_queue()[0].case
        with patch.object(services, "build_cases", return_value=(case, case)):
            with self.assertRaisesRegex(WorkbenchDataError, "duplicate_case_key"):
                services.build_queue()
