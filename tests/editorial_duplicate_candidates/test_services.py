"""Independent synthetic comparisons and exact authority/provenance checks."""

import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_duplicate_candidates import services
from apps.editorial_queue.services import QueueRow, build_queue_catalog
from apps.editorial_workbench.services import WorkbenchCase


def synthetic_row(ordinal, question, external_id="SYN-REPEATED"):
    original = {"external_id": external_id, "question": question}
    raw = json.dumps(original, ensure_ascii=False, sort_keys=True)
    digest = sha256(raw.encode("utf-8")).hexdigest()
    case = WorkbenchCase(
        key=f"intake-{ordinal}",
        external_id=external_id,
        question=question if isinstance(question, str) else None,
        prepared_clip_url=None,
        raw_source=raw,
        source_start=0,
        source_end=len(raw.encode("utf-8")),
        payload_sha256=digest,
        fixture_label="Invented regression fixture",
        status="blocked",
        status_label="Synthetic blocked input",
        issues=(),
        record=None,
        references=(),
    )
    return QueueRow(case, "original", (), 0, 0, digest)


def detect(*rows):
    return services.detect_candidates(rows, synthetic_fixtures_only=True)


class DuplicateServiceTests(unittest.TestCase):
    def test_exact_and_normalized_pairs_are_distinct_and_explainable(self):
        rows = (
            synthetic_row(1, "سُؤالٌ\r\n e\u0301", "SYN-A"),
            synthetic_row(2, "سُؤالٌ\r\n e\u0301", "SYN-B"),
            synthetic_row(3, "سؤال é", "SYN-C"),
        )
        report = detect(*rows)
        self.assertEqual(len(report.candidates), 3)
        kinds = {(p.left_key, p.right_key): p.kind for p in report.candidates}
        self.assertEqual(kinds[("intake-1", "intake-2")], "exact_text")
        self.assertEqual(kinds[("intake-1", "intake-3")], "normalized_text")
        self.assertEqual(kinds[("intake-2", "intake-3")], "normalized_text")
        self.assertTrue(all(pair.reasons for pair in report.candidates))
        self.assertEqual(report.json_bytes(), detect(*reversed(rows)).json_bytes())

    def test_repeated_external_id_does_not_create_text_match_or_collapse_cases(self):
        report = detect(synthetic_row(1, "سؤال أول"), synthetic_row(2, "سؤال ثان"))
        self.assertEqual(len(report.cases), 2)
        self.assertEqual(report.candidates, ())
        exact = detect(synthetic_row(1, "سؤال"), synthetic_row(2, "سؤال"))
        self.assertEqual(len(exact.cases), 2)
        self.assertEqual(len(exact.candidates), 1)

    def test_all_pairs_are_returned_without_self_pairs_or_transitive_identity_links(self):
        report = detect(*(synthetic_row(i, "سؤال ثابت") for i in range(1, 5)))
        pairs = [(p.left_key, p.right_key) for p in report.candidates]
        self.assertEqual(len(pairs), 6)
        self.assertEqual(len(set(pairs)), 6)
        self.assertTrue(all(left != right for left, right in pairs))
        self.assertNotIn("merged", report.to_dict())

    def test_empty_and_invalid_text_remain_visible_but_never_match(self):
        report = detect(
            *(synthetic_row(i, text) for i, text in enumerate((None, 42, "", " \r\n", "ًْ"), 1))
        )
        self.assertEqual(len(report.cases), 5)
        self.assertEqual(report.candidates, ())

    def test_explicit_synthetic_guard_runs_before_consuming_inputs(self):
        def forbidden():
            self.fail("input must not be consumed without acknowledgement")
            yield

        for flag in (False, None, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(services.DuplicateCandidateError):
                services.detect_candidates(forbidden(), synthetic_fixtures_only=flag)
        with patch.object(services, "build_queue_catalog") as build:
            with self.assertRaises(services.DuplicateCandidateError):
                services.build_duplicate_report()
            build.assert_not_called()

    def test_duplicate_canonical_keys_and_bad_source_hashes_fail_closed(self):
        row = synthetic_row(1, "سؤال")
        for inputs in (
            (row, row),
            (row, replace(row, case=replace(row.case, question="changed"))),
            (replace(row, source_sha256="0" * 64),),
            (replace(row, case=replace(row.case, payload_sha256="invalid")),),
            (replace(row, case=replace(row.case, source_end=1)),),
            (replace(row, case=replace(row.case, question="wrong projection")),),
            (object(),),
        ):
            with (
                self.subTest(inputs=len(inputs)),
                self.assertRaises(services.DuplicateCandidateError),
            ):
                detect(*inputs)

    def test_duplicate_source_fields_fail_closed_in_fixed_rows_and_history(self):
        # Regression for the focused review: correct hashes do not remove JSON ambiguity.
        row = synthetic_row(1, "B")
        for raw in (
            '{"external_id":"SYN-REPEATED","question":"A","question":"B"}',
            '{"external_id":"A","external_id":"SYN-REPEATED","question":"B"}',
            '{"external_id":"SYN-REPEATED","question":"B","nested":{"x":1,"x":2}}',
        ):
            digest = sha256(raw.encode()).hexdigest()
            corrupted = replace(
                row,
                source_sha256=digest,
                case=replace(
                    row.case,
                    raw_source=raw,
                    payload_sha256=digest,
                    source_end=len(raw.encode()),
                ),
            )
            with self.subTest(raw=raw), self.assertRaises(services.DuplicateCandidateError):
                detect(corrupted, synthetic_row(2, "B"))
        raw = '{"items":[],"items":[{"external_id":"SYN-REPEATED","question":"B"}]}'
        digest = sha256(raw.encode()).hexdigest()
        history = replace(
            row,
            source_sha256=digest,
            case=replace(
                row.case,
                key="history",
                raw_source=raw,
                payload_sha256=digest,
                source_start=None,
                source_end=None,
            ),
        )
        with self.assertRaises(services.DuplicateCandidateError):
            detect(history, synthetic_row(2, "B"))

    def test_non_json_numeric_constants_fail_closed_without_echoing_source(self):
        row = synthetic_row(1, "B")
        for constant in ("NaN", "Infinity", "-Infinity"):
            raw = '{"external_id":"SYN-REPEATED","question":"B","extra":' + constant + "}"
            digest = sha256(raw.encode()).hexdigest()
            corrupted = replace(
                row,
                source_sha256=digest,
                case=replace(
                    row.case,
                    raw_source=raw,
                    payload_sha256=digest,
                    source_end=len(raw.encode()),
                ),
            )
            with (
                self.subTest(constant=constant),
                self.assertRaises(services.DuplicateCandidateError) as caught,
            ):
                detect(corrupted)
            self.assertNotIn("SYN-REPEATED", str(caught.exception))

    def test_bounds_on_rows_text_aggregate_source_and_candidate_explosion(self):
        unique = (synthetic_row(i, f"synthetic {i}") for i in range(1, 1002))
        with self.assertRaises(services.DuplicateCandidateError):
            services.detect_candidates(unique, synthetic_fixtures_only=True)
        with self.assertRaises(services.DuplicateCandidateError):
            detect(synthetic_row(1, "x" * 65537))
        with self.assertRaises(services.DuplicateCandidateError):
            detect(*(synthetic_row(i, "سؤال") for i in range(1, 144)))
        with self.assertRaises(services.DuplicateCandidateError):
            detect(*(synthetic_row(i, "x" * 60000 + str(i)) for i in range(1, 38)))

    def test_built_in_adapter_uses_authoritative_rows_without_mutation(self):
        catalog = build_queue_catalog()
        before = copy.deepcopy(catalog)
        with patch.object(services, "build_queue_catalog", return_value=catalog) as build:
            report = services.build_duplicate_report(synthetic_fixtures_only=True)
        build.assert_called_once_with()
        self.assertEqual(catalog, before)
        self.assertEqual(len(report.cases), 20)
        self.assertIn("MALFORMED_INPUT", report.json_bytes().decode())
        self.assertIn("synthetic-malformed", report.json_bytes().decode())
        self.assertEqual(
            report.json_bytes(),
            services.build_duplicate_report(synthetic_fixtures_only=True).json_bytes(),
        )
        payload = report.to_dict()
        self.assertEqual(json.loads(report.json_bytes()), json.loads(json.dumps(payload)))
        indexed = {case.source.case_key: case for case in report.cases}
        for row in catalog.rows:
            compared = indexed[row.case.key]
            self.assertEqual(compared.text, row.case.question)
            self.assertEqual(compared.source.batch_id, row.batch_id)
            self.assertEqual(compared.source.external_id, row.case.external_id)
            self.assertEqual(compared.source.source_sha256, row.source_sha256)
            self.assertEqual(compared.source.payload_sha256, row.case.payload_sha256)
            self.assertEqual(compared.source.source_start, row.case.source_start)
            self.assertEqual(compared.source.source_end, row.case.source_end)
            if row.case.question is not None:
                self.assertEqual(
                    compared.text_sha256, sha256(row.case.question.encode("utf-8")).hexdigest()
                )
        self.assertEqual(indexed["batch-synthetic-jsonl-2"].source.field, "title")
        self.assertEqual(
            indexed["batch-synthetic-csv-4"].source.csv_extra_cells, ("overflow-synthetic",)
        )
        shared = {"batch-synthetic-csv-2", "batch-synthetic-json-1"}
        self.assertFalse(any({p.left_key, p.right_key} == shared for p in report.candidates))

    def test_cross_fixed_and_prepared_candidate_preserves_separate_source_kinds(self):
        prepared = next(
            row for row in build_queue_catalog().rows if row.case.key == "batch-synthetic-csv-1"
        )
        normalized = services.normalize_text(prepared.case.question)
        report = detect(prepared, synthetic_row(99, normalized, "SYN-CROSS-SOURCE"))
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].kind, "normalized_text")
        self.assertEqual(
            {case.source.source_kind for case in report.cases},
            {"serialized_prepared_row", "original_utf8_slice"},
        )
        self.assertEqual(len({case.source.case_key for case in report.cases}), 2)
        self.assertEqual(len({case.source.payload_sha256 for case in report.cases}), 2)

    def test_prepared_identity_original_and_offsets_cannot_be_rewritten(self):
        row = next(
            row for row in build_queue_catalog().rows if row.case.key == "batch-synthetic-csv-1"
        )
        for changes in (
            {"batch_id": "different"},
            {"row_ordinal": 2},
            {"row_ordinal": True},
            {"key": "intake-1"},
            {"original": {"question": "wrong"}},
            {"source_start": 0},
            {"external_id": "wrong"},
            {"csv_extra_cells": ["not-a-tuple"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(services.DuplicateCandidateError):
                detect(replace(row, case=replace(row.case, **changes)))

    def test_exclusions_and_transformation_reasons_are_explicit(self):
        report = detect(
            synthetic_row(1, None),
            synthetic_row(2, " \r\n"),
            synthetic_row(3, "؟!"),
            synthetic_row(4, "سُؤال\r\ne\u0301"),
            synthetic_row(5, "سؤال é"),
        )
        self.assertEqual(
            [case.exclusion_reason for case in report.cases[:3]],
            ["missing_or_non_text_question", "empty_normalized_text", "no_letters_or_numbers"],
        )
        self.assertEqual(
            set(report.candidates[0].reasons),
            {
                "equal_after_conservative_normalization",
                "unicode_nfc",
                "arabic_vowel_marks_removed",
                "whitespace_collapsed",
            },
        )

    def test_result_is_immutable_and_json_projection_does_not_mutate_it(self):
        report = detect(synthetic_row(1, "سؤال"), synthetic_row(2, "سؤال"))
        original = report.json_bytes()
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            report.candidates = ()
        projected = report.to_dict()
        projected.clear()
        self.assertEqual(report.json_bytes(), original)
