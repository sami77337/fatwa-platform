"""Behavioral contracts over explicitly fabricated, manually labelled text."""

import csv
import hashlib
import io
import json
import unittest

from apps import transcript_pipeline as pipeline
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch


def row(**changes):
    return (
        dict(
            source_id="synthetic-source",
            segment_id="q1",
            pair_id="pair1",
            kind="question",
            start_ms=10,
            end_ms=1010,
            text="  سُؤالٌ اصطناعيٌّ\r\nللاختبار فقط؟  ",
            provenance="manual-fabricated-fixture-v1",
            fabricated=True,
        )
        | changes
    )


def answer(**changes):
    return row(
        segment_id="a1",
        kind="answer",
        start_ms=1010,
        end_ms=2001,
        text="جوابٌ اصطناعيٌّ للاختبار، وليس فتوى.",
        **changes,
    )


def encode(rows, suffix=".json"):
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(dict(r, fabricated="true") for r in rows)
        return stream.getvalue().encode("utf-8")
    if suffix == ".jsonl":
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")
    return json.dumps(rows, ensure_ascii=False).encode("utf-8")


class TranscriptTests(unittest.TestCase):
    def process(self, rows, suffix=".json"):
        return pipeline.segment_file(encode(rows, suffix), suffix, synthetic_fixtures_only=True)

    def test_exact_arabic_intervals_and_original_file_hash_in_all_formats(self):
        rows = [row(), answer()]
        for suffix in (".csv", ".json", ".jsonl"):
            with self.subTest(suffix=suffix):
                raw = encode(rows, suffix)
                batch = pipeline.segment_file(raw, suffix, synthetic_fixtures_only=True)
                report = json.loads(batch.json_bytes())
                self.assertEqual(report["input_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(report["segments"], rows)
                self.assertEqual(report["pairs"][0]["answer_segment_id"], "a1")
                self.assertFalse(report["human_editing_performed"])
                self.assertEqual(batch.json_bytes(), batch.json_bytes())

    def test_prepared_export_roundtrips_real_fast4_without_invented_answers_or_media(self):
        batch = self.process([row(), answer()])
        exported = json.loads(batch.prepared_bytes())
        self.assertEqual(exported["schema"], "fatwa.prepared-intake.v1")
        self.assertEqual(len(exported["items"]), 1)
        item = exported["items"][0]
        self.assertEqual(item["question"], row()["text"])
        self.assertEqual(item["reference_links"], [])
        self.assertEqual(item["staff_notes"], "")
        self.assertEqual(item["prepared_clip_url"], "")
        self.assertNotIn("answer", item)
        prepared = prepare_batch(batch.prepared_bytes(), synthetic_fixtures_only=True)
        self.assertEqual(prepared.drafts, ())
        self.assertEqual(
            prepared.report["items"][0]["statuses"],
            ["needs-editor-review", "references-unverified"],
        )
        self.assertEqual(prepared.report["items"][0]["original"]["question"], row()["text"])
        self.assertEqual(
            json.loads(batch.json_bytes())["pairs"][0]["external_id"], item["external_id"]
        )

    def test_question_without_answer_is_retained_and_marked_missing(self):
        batch = self.process([row()])
        pair = json.loads(batch.json_bytes())["pairs"][0]
        self.assertIsNone(pair["answer_segment_id"])
        self.assertEqual(pair["status"], "answer-not-supplied")

    def test_hashes_and_export_are_order_and_format_independent_but_content_sensitive(self):
        rows = [row(), answer()]
        baseline = self.process(rows)
        for suffix in (".json", ".csv", ".jsonl"):
            other = self.process(list(reversed(rows)), suffix)
            self.assertEqual(baseline.prepared_bytes(), other.prepared_bytes())
            self.assertEqual(
                json.loads(baseline.json_bytes())["sources"],
                json.loads(other.json_bytes())["sources"],
            )
        changed = self.process([row(text="سؤال اصطناعي مختلف"), answer()])
        self.assertNotEqual(
            json.loads(baseline.json_bytes())["sources"],
            json.loads(changed.json_bytes())["sources"],
        )

    def test_synthetic_acknowledgement_is_strict_and_every_row_is_marked(self):
        for ack in (False, 1, "true", None):
            with self.subTest(ack=ack), self.assertRaises(ValidationError):
                pipeline.segment_file(encode([row()]), ".json", synthetic_fixtures_only=ack)
        for marker in (False, 1, "true", None):
            with self.subTest(marker=marker), self.assertRaises(ValidationError):
                self.process([row(fabricated=marker)])

    def test_timestamp_and_text_boundaries_reject_lossy_coercion(self):
        invalid = [
            dict(start_ms=True),
            dict(start_ms=1.0),
            dict(start_ms="10"),
            dict(start_ms=-1),
            dict(end_ms=10),
            dict(end_ms=9),
            dict(end_ms=86400001),
            dict(end_ms=None),
            dict(text=" "),
            dict(text="x" * 20001),
            dict(text="a\x00b"),
            dict(provenance=""),
            dict(source_id=" spaced "),
            dict(segment_id="x\n"),
            dict(kind="unlabelled"),
            dict(extra="unknown"),
        ]
        for changes in invalid:
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                self.process([row(**changes)])
        self.process([row(start_ms=0, end_ms=86400000, text="x" * 20000)])

    def test_all_overlaps_rejected_but_adjacent_and_different_sources_allowed(self):
        for start, end in ((0, 11), (11, 100), (9, 1011), (10, 1010), (1009, 2000)):
            with self.subTest(start=start), self.assertRaisesRegex(ValidationError, "overlapping"):
                self.process(
                    [row(), row(segment_id="q2", pair_id="p2", start_ms=start, end_ms=end)]
                )
        self.process([row(), row(segment_id="q2", pair_id="p2", start_ms=1010, end_ms=2010)])
        self.process([row(), row(source_id="second")])

    def test_duplicate_segments_ambiguous_pair_or_orphan_answer_fail_closed(self):
        bad_batches = [
            [row(), row(start_ms=1010, end_ms=2010)],
            [row(), row(segment_id="q2", start_ms=1010, end_ms=2010)],
            [answer()],
            [row(start_ms=2001, end_ms=3000), answer()],
            [row(), answer(), row(segment_id="a2", kind="answer", start_ms=2001, end_ms=3000)],
        ]
        for rows in bad_batches:
            with self.subTest(rows=len(rows)), self.assertRaises(ValidationError):
                self.process(rows)

    def test_parser_rejects_malformed_and_unbounded_inputs_without_echoing_text(self):
        invalid = [
            (b"[]", ".json"),
            (b"{}", ".json"),
            (b"\xff", ".json"),
            (b'{"secret":"x","secret":"y"}', ".json"),
            (b"[NaN]", ".json"),
            (b'["\\ud800"]', ".json"),
            (b"source_id,source_id\na,b\n", ".csv"),
            (b"[" * 2000 + b"]" * 2000, ".json"),
            (encode([row()]), ".mp3"),
            (b" " * 1000001, ".json"),
            (encode([row()] * 1001), ".json"),
        ]
        for raw, suffix in invalid:
            with (
                self.subTest(suffix=suffix, size=len(raw)),
                self.assertRaises(ValidationError) as caught,
            ):
                pipeline.segment_file(raw, suffix, synthetic_fixtures_only=True)
            self.assertNotIn("secret", str(caught.exception))

    def test_csv_ragged_rows_noncanonical_timestamps_and_false_marker_rejected(self):
        good = encode([row()], ".csv")
        for raw in (
            good + b"extra\n",
            good.replace(b",10,", b",1e1,"),
            good.replace(b",10,", b",010,"),
            good.replace(b",true", b",false"),
        ):
            with self.subTest(raw=len(raw)), self.assertRaises(ValidationError):
                pipeline.segment_file(raw, ".csv", synthetic_fixtures_only=True)

    def test_json_envelope_bom_and_unicode_separators_are_preserved(self):
        rows = [row(text="نص اصطناعي\u2028اختباري\u2029فقط")]
        raw = b"\xef\xbb\xbf" + json.dumps(
            dict(schema="fatwa.synthetic-transcript.v1", items=rows), ensure_ascii=False
        ).encode("utf-8")
        batch = pipeline.segment_file(raw, ".JSON", synthetic_fixtures_only=True)
        self.assertEqual(json.loads(batch.json_bytes())["segments"], rows)
        self.assertEqual(json.loads(self.process(rows, ".jsonl").json_bytes())["segments"], rows)

    def test_exact_input_and_row_limits_remain_usable(self):
        rows = [
            row(segment_id=f"q{i}", pair_id=f"p{i}", start_ms=i, end_ms=i + 1) for i in range(1000)
        ]
        raw = encode(rows)
        raw += b" " * (1_000_000 - len(raw))
        batch = pipeline.segment_file(raw, ".json", synthetic_fixtures_only=True)
        self.assertEqual(len(json.loads(batch.prepared_bytes())["items"]), 1000)
        with self.assertRaises(ValidationError):
            pipeline.segment_file(raw + b" ", ".json", synthetic_fixtures_only=True)

    def test_prepared_expansion_cannot_exceed_downstream_byte_limit(self):
        # CSV is compact while JSON must escape every tab; retain exact text or reject.
        rows = [
            row(
                segment_id=f"q{i}",
                pair_id=f"p{i}",
                start_ms=i,
                end_ms=i + 1,
                text="س" + "\t" * 19_999,
            )
            for i in range(30)
        ]
        raw = encode(rows, ".csv")
        self.assertLess(len(raw), 1_000_000)
        with self.assertRaisesRegex(ValidationError, "prepared_byte_limit_exceeded"):
            pipeline.segment_file(raw, ".csv", synthetic_fixtures_only=True)
