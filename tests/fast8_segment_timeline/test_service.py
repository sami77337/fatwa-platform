"""Executable timing, exact-text and transcript compatibility contracts."""

import csv
import hashlib
import io
import json
import unittest

from apps.fast8_segment_timeline.service import diagnose_file
from apps.transcript_pipeline import ValidationError, segment_file


def row(**changes):
    return (
        dict(
            source_id="fabricated-video",
            segment_id="q1",
            pair_id="p1",
            kind="question",
            start_ms=0,
            end_ms=1001,
            text="  سُؤالٌ اصطناعيٌّ\r\nللاختبار فقط؟\u2028  ",
            provenance="entirely fabricated manual timing fixture",
            fabricated=True,
        )
        | changes
    )


def answer(**changes):
    return row(
        **(
            dict(
                segment_id="a1",
                kind="answer",
                start_ms=1001,
                end_ms=2003,
                text="نص اصطناعي لا يمثل جواباً شرعياً.",
            )
            | changes
        )
    )


def encode(rows, suffix=".json"):
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(
            dict(item, fabricated="true" if item["fabricated"] is True else "false")
            for item in rows
        )
        return stream.getvalue().encode("utf-8")
    if suffix == ".jsonl":
        return "\r\n".join(json.dumps(item, ensure_ascii=False) for item in rows).encode("utf-8")
    return json.dumps(rows, ensure_ascii=False).encode("utf-8")


def diagnose(rows, suffix=".json", **kwargs):
    return diagnose_file(encode(rows, suffix), suffix, synthetic_fixtures_only=True, **kwargs)


def report(rows, **kwargs):
    return json.loads(diagnose(rows, **kwargs).json_bytes())


class TimelineServiceTests(unittest.TestCase):
    def codes(self, value):
        return {finding["code"] for finding in value["findings"]}

    def test_exact_question_label_crlf_unicode_and_millisecond_cues_all_formats(self):
        for suffix in (".json", ".csv", ".jsonl"):
            with self.subTest(suffix=suffix):
                batch = diagnose([row(), answer()], suffix)
                cues = json.loads(batch.cue_json_bytes())
                self.assertEqual(cues["mode"], "MANUAL")
                self.assertEqual(
                    [item["question_label"] for item in cues["cues"]],
                    [row()["text"], row()["text"]],
                )
                self.assertEqual(cues["cues"][0]["end_ms"], 1001)
                self.assertEqual(cues["cues"][0]["end_time"], "00:00:01.001")
                self.assertEqual(cues["cues"][1]["end_time"], "00:00:02.003")
                csv_rows = list(
                    csv.DictReader(io.StringIO(batch.cue_csv_bytes().decode("utf-8"), newline=""))
                )
                self.assertEqual(csv_rows[0]["question_label"], row()["text"])
                self.assertEqual(csv_rows[1]["question_label"], row()["text"])

    def test_source_hash_matches_existing_pipeline_without_modifying_original_rows(self):
        rows = [answer(), row()]
        for suffix in (".json", ".csv", ".jsonl"):
            with self.subTest(suffix=suffix):
                raw = encode(rows, suffix)
                baseline = json.loads(
                    segment_file(raw, suffix, synthetic_fixtures_only=True).json_bytes()
                )
                result = json.loads(
                    diagnose_file(raw, suffix, synthetic_fixtures_only=True).json_bytes()
                )
                self.assertEqual(result["input_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(
                    result["sources"][0]["source_sha256"], baseline["sources"][0]["source_sha256"]
                )
                actual = [
                    {key: value for key, value in item.items() if key in rows[0]}
                    for item in result["segments"]
                ]
                self.assertEqual(actual, rows)

    def test_segment_hash_is_stable_across_format_and_changes_with_exact_text(self):
        digests = []
        for suffix in (".json", ".csv", ".jsonl"):
            value = json.loads(diagnose([row()], suffix).json_bytes())
            digests.append(value["segments"][0]["segment_sha256"])
        self.assertEqual(len(set(digests)), 1)
        changed = report([row(text=row()["text"].replace("\r\n", "\n"))])
        self.assertNotEqual(digests[0], changed["segments"][0]["segment_sha256"])

    def test_reports_and_cues_are_byte_deterministic(self):
        first = diagnose([row(), answer()])
        second = diagnose([row(), answer()])
        for method in ("json_bytes", "cue_json_bytes", "cue_csv_bytes"):
            self.assertEqual(getattr(first, method)(), getattr(second, method)())

    def test_noninteger_timestamps_are_diagnostics_and_never_rounded(self):
        for field in ("start_ms", "end_ms"):
            for invalid in (True, False, 1.1, 1001.0, "1001", None):
                with self.subTest(field=field, invalid=invalid):
                    batch = diagnose([row(**{field: invalid})])
                    value = json.loads(batch.json_bytes())
                    self.assertIn("integer_milliseconds_required", self.codes(value))
                    self.assertFalse(value["cues_allowed"])
                    with self.assertRaises(ValidationError):
                        batch.cue_json_bytes()
                    with self.assertRaises(ValidationError):
                        batch.cue_csv_bytes()

    def test_invalid_and_upper_bound_spans_report_original_row_numbers(self):
        for start, end in ((-1, 10), (10, 10), (11, 10), (0, 86400001)):
            with self.subTest(start=start, end=end):
                value = report(
                    [row(), row(segment_id="bad", pair_id="bad", start_ms=start, end_ms=end)]
                )
                errors = [item for item in value["findings"] if item["code"] == "invalid_interval"]
                self.assertEqual([item["row"] for item in errors], [2])
                self.assertTrue(errors[0]["message"])
                self.assertFalse(value["cues_allowed"])
        accepted = json.loads(diagnose([row(start_ms=86399999, end_ms=86400000)]).cue_json_bytes())
        self.assertEqual(accepted["cues"][0]["end_time"], "24:00:00.000")

    def test_adjacent_intervals_are_not_gaps_or_overlaps(self):
        value = report([row(), answer()])
        self.assertFalse(self.codes(value) & {"gap", "overlap", "duplicate_span"})
        self.assertTrue(value["cues_allowed"])

    def test_nested_overlap_uses_coverage_frontier_not_previous_short_segment(self):
        value = report(
            [
                row(end_ms=100),
                row(segment_id="q2", pair_id="p2", start_ms=10, end_ms=20),
                row(segment_id="q3", pair_id="p3", start_ms=30, end_ms=40),
            ]
        )
        overlaps = [item for item in value["findings"] if item["code"] == "overlap"]
        self.assertEqual({item["row"] for item in overlaps}, {2, 3})
        self.assertNotIn("gap", self.codes(value))
        self.assertFalse(value["cues_allowed"])

    def test_gap_is_actionable_and_does_not_infer_a_new_question(self):
        value = report([row(end_ms=10), answer(start_ms=15, end_ms=20)])
        gaps = [item for item in value["findings"] if item["code"] == "gap"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["row"], 2)
        self.assertEqual(gaps[0]["related_row"], 1)
        self.assertEqual(len(value["segments"]), 2)
        self.assertTrue(value["cues_allowed"])

    def test_duplicate_spans_and_ids_are_separate_findings(self):
        value = report([row(), row(pair_id="p2")])
        self.assertTrue({"duplicate_span", "duplicate_segment_id", "overlap"} <= self.codes(value))
        self.assertFalse(value["cues_allowed"])

    def test_pair_order_is_reported_even_when_spans_do_not_overlap(self):
        value = report([answer(start_ms=0, end_ms=10), row(start_ms=10, end_ms=20)])
        self.assertIn("answer_must_follow_question", self.codes(value))
        self.assertNotIn("overlap", self.codes(value))
        self.assertFalse(value["cues_allowed"])

    def test_missing_and_ambiguous_questions_block_cues(self):
        for rows, code in (
            ([answer()], "question_required"),
            ([row(), row(segment_id="q2", start_ms=1001, end_ms=2000)], "ambiguous_pair"),
        ):
            with self.subTest(code=code):
                value = report(rows)
                self.assertIn(code, self.codes(value))
                self.assertFalse(value["cues_allowed"])

    def test_question_only_keeps_exact_label_and_marks_answer_not_supplied(self):
        batch = diagnose([row()])
        self.assertIn("answer_not_supplied", self.codes(json.loads(batch.json_bytes())))
        self.assertEqual(
            json.loads(batch.cue_json_bytes())["cues"][0]["question_label"], row()["text"]
        )

    def test_source_scoped_ids_pairs_and_timelines_never_join_across_sources(self):
        rows = [row(), row(source_id="second-fabricated", text="سؤال ثانٍ اصطناعي")]
        value = report(rows)
        self.assertFalse(
            self.codes(value)
            & {"duplicate_span", "duplicate_segment_id", "overlap", "ambiguous_pair"}
        )
        cues = json.loads(diagnose(rows).cue_json_bytes())["cues"]
        self.assertEqual(
            {item["source_id"]: item["question_label"] for item in cues},
            {item["source_id"]: item["text"] for item in rows},
        )

    def test_explicit_source_duration_is_inclusive_and_missing_duration_not_invented(self):
        value = report([row()], source_durations_ms={"fabricated-video": 1001})
        self.assertNotIn("duration_exceeded", self.codes(value))
        over = report([row()], source_durations_ms={"fabricated-video": 1000})
        self.assertIn("duration_exceeded", self.codes(over))
        self.assertFalse(over["cues_allowed"])
        missing = report([row()])
        self.assertIsNone(missing["sources"][0]["duration_ms"])

    def test_invalid_duration_types_and_unknown_source_fail_closed(self):
        for durations in (
            {"fabricated-video": True},
            {"fabricated-video": 1.5},
            {"fabricated-video": 0},
            {"fabricated-video": 86400001},
            {"unknown-source": 1001},
        ):
            with self.subTest(durations=durations), self.assertRaises(ValidationError):
                diagnose([row()], source_durations_ms=durations)

    def test_invalid_source_identity_with_declared_duration_has_controlled_rejection(self):
        with self.assertRaises(ValidationError):
            diagnose([row(source_id=[])], source_durations_ms={"fabricated-video": 1001})

    def test_initial_and_trailing_gaps_use_declared_bounds(self):
        value = report([row(start_ms=10, end_ms=20)], source_durations_ms={"fabricated-video": 30})
        gaps = [item for item in value["findings"] if item["code"] == "gap"]
        self.assertEqual([(item["start_ms"], item["end_ms"]) for item in gaps], [(0, 10), (20, 30)])

    def test_out_of_order_input_is_diagnosed_but_exact_cues_sort_chronologically(self):
        batch = diagnose([answer(), row()])
        self.assertIn("input_order", self.codes(json.loads(batch.json_bytes())))
        self.assertEqual(
            [cue["segment_id"] for cue in json.loads(batch.cue_json_bytes())["cues"]], ["q1", "a1"]
        )

    def test_csv_precision_tokens_are_never_silently_coerced(self):
        for value in ("01", "+1", "1.0", "1e3", "١", " 1"):
            with self.subTest(value=value):
                found = json.loads(diagnose([row(start_ms=value)], ".csv").json_bytes())
                self.assertIn("integer_milliseconds_required", self.codes(found))
                self.assertFalse(found["cues_allowed"])

    def test_fabrication_requires_both_explicit_caller_and_every_row(self):
        for ack in (False, 1, "true", None):
            with self.subTest(ack=ack), self.assertRaises(ValidationError):
                diagnose_file(encode([row()]), ".json", synthetic_fixtures_only=ack)
        for marker in (False, 1, "true", None):
            with self.subTest(marker=marker), self.assertRaises(ValidationError):
                diagnose([row(), answer(fabricated=marker)])

    def test_malformed_schema_encoding_and_input_limits_fail_closed(self):
        for raw, suffix in (
            (b"[]", ".json"),
            (b"{", ".json"),
            (b"\xff", ".json"),
            (b"{}", ".wav"),
            (b" " * 1000001, ".json"),
            (encode([row(extra="not-contract")]), ".json"),
        ):
            with self.subTest(suffix=suffix, size=len(raw)), self.assertRaises(ValidationError):
                diagnose_file(raw, suffix, synthetic_fixtures_only=True)


if __name__ == "__main__":
    unittest.main()
