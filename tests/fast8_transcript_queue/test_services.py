"""Identity-preserving adapters over real transcript/preparation/queue services."""

import csv
import io
import json
import unittest
from dataclasses import FrozenInstanceError
from hashlib import sha256

from apps.editorial_queue.services import build_queue
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from apps.transcript_pipeline import segment_file


def segments():
    common = dict(
        source_id="مصدر-اصطناعي",
        pair_id="pair-1",
        provenance="FAST8 fabricated manual spans; no recording or real question",
        fabricated=True,
    )
    return [
        dict(
            common,
            segment_id="q1",
            kind="question",
            start_ms=17,
            end_ms=1017,
            text="  سُؤالٌ اصطناعيٌّ\r\nللتجربة فقط؟  ",
        ),
        dict(
            common,
            segment_id="a1",
            kind="answer",
            start_ms=1017,
            end_ms=2019,
            text="  نصّ جوابٍ مُختلق\r\nدليل مصدر فقط، ليس فتوى.  ",
        ),
    ]


def encode(rows, suffix=".json"):
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(dict(row, fabricated="true") for row in rows)
        return stream.getvalue().encode("utf-8")
    if suffix == ".jsonl":
        return "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode("utf-8")
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")


class TranscriptQueueTests(unittest.TestCase):
    def build(self, rows=None, suffix=".json", **kwargs):
        # Local import lets the first red run identify the missing public adapter.
        from apps.fast8_transcript_queue.services import build_transcript_queue

        return build_transcript_queue(
            encode(segments() if rows is None else rows, suffix),
            suffix,
            synthetic_fixtures_only=True,
            **kwargs,
        )

    def test_exact_evidence_and_both_actual_source_contracts(self):
        for suffix in (".json", ".csv", ".jsonl"):
            with self.subTest(suffix=suffix):
                raw = encode(segments(), suffix)
                actual = self.build(suffix=suffix)
                transcript = segment_file(raw, suffix, synthetic_fixtures_only=True)
                report = json.loads(transcript.json_bytes())
                prepared = prepare_batch(transcript.prepared_bytes(), synthetic_fixtures_only=True)
                (entry,) = actual.entries
                self.assertEqual(actual.prepared_bytes(), transcript.prepared_bytes())
                self.assertEqual(json.loads(actual.json_bytes())["prepared"], prepared.report)
                self.assertEqual(entry.source_id, "مصدر-اصطناعي")
                self.assertEqual(entry.pair_id, "pair-1")
                self.assertEqual(entry.source_sha256, report["sources"][0]["source_sha256"])
                self.assertEqual(entry.input_sha256, sha256(raw).hexdigest())
                self.assertEqual(
                    entry.prepared_payload_sha256, sha256(actual.prepared_bytes()).hexdigest()
                )
                self.assertEqual(entry.external_id, report["pairs"][0]["external_id"])
                self.assertEqual(entry.question.segment_id, "q1")
                self.assertEqual((entry.question.start_ms, entry.question.end_ms), (17, 1017))
                self.assertEqual(entry.question.text, segments()[0]["text"])
                self.assertEqual((entry.answer.start_ms, entry.answer.end_ms), (1017, 2019))
                self.assertEqual(entry.answer.text, segments()[1]["text"])
                self.assertEqual(json.loads(entry.question.json_bytes()), segments()[0])
                self.assertEqual(
                    entry.question.sha256, sha256(entry.question.json_bytes()).hexdigest()
                )
                self.assertEqual(entry.answer.sha256, sha256(entry.answer.json_bytes()).hexdigest())

    def test_ephemeral_queue_retains_missing_media_and_unverified_references(self):
        actual = self.build()
        (row,) = actual.rows
        (entry,) = actual.entries
        self.assertEqual(row.case.question, segments()[0]["text"])
        self.assertEqual(row.case.payload_sha256, entry.input_sha256)
        self.assertEqual(row.case.raw_source.encode("utf-8"), entry.question.json_bytes())
        self.assertEqual(row.source_sha256, entry.question.sha256)
        self.assertEqual(row.reference_status, "missing")
        self.assertEqual(row.case.references, ())
        self.assertEqual(row.case.status, "review")
        self.assertEqual(row.history, ())
        self.assertIsNone(row.case.record)
        self.assertIsNone(row.case.source_start)
        self.assertIsNone(row.case.source_end)
        report = json.loads(actual.json_bytes())
        self.assertEqual(report["storage"], "EPHEMERAL")
        self.assertEqual(report["origin"], "transcript")
        self.assertFalse(report["publication_allowed"])
        self.assertFalse(report["human_editing_performed"])
        self.assertEqual(report["answer_role"], "SOURCE_EVIDENCE_ONLY")
        self.assertEqual(report["gates"]["U03/U10"], "OWNER_APPROVAL_PENDING")
        self.assertNotIn(segments()[1]["text"], str(json.loads(actual.prepared_bytes())))

    def test_fixed_twenty_cases_keep_their_exact_identity_and_no_transcript_links(self):
        before = build_queue()
        self.assertEqual(len(before), 20)
        actual = self.build()
        self.assertEqual(build_queue(), before)
        self.assertTrue(
            {row.case.key for row in before}.isdisjoint(row.case.key for row in actual.rows)
        )
        self.assertTrue(
            {row.batch_id for row in before}.isdisjoint(row.batch_id for row in actual.rows)
        )

    def test_selection_reuses_queue_filters_and_scopes_identity_by_source(self):
        rows = segments()
        rows += [dict(row, source_id="second") for row in segments()]
        actual = self.build(rows)
        self.assertEqual(len({row.case.key for row in actual.rows}), 2)
        first, second = actual.rows
        selected = actual.select(key=first.case.key, status="review-without-draft", refs="missing")
        self.assertEqual(selected.rows, actual.rows)
        self.assertEqual(selected.position, 1)
        self.assertIsNone(selected.previous)
        self.assertEqual(selected.next, second)
        self.assertEqual(actual.select(q="سُؤالٌ").rows, actual.rows)
        self.assertEqual(actual.select(status="ready").rows, ())
        self.assertIsNone(actual.select(key="history").selected)
        for entry in actual.entries:
            self.assertIs(
                actual.resolve(entry.source_id, entry.pair_id, entry.source_sha256), entry
            )

    def test_missing_or_wrong_origin_reference_never_falls_back(self):
        actual = self.build()
        (entry,) = actual.entries
        for identity in (
            (entry.source_id, "missing", entry.source_sha256),
            ("missing", entry.pair_id, entry.source_sha256),
            (entry.source_id, entry.pair_id, "0" * 64),
            (entry.source_id, entry.pair_id, None),
        ):
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                actual.resolve(*identity)

    def test_missing_answer_is_explicit_not_an_invented_answer_reference(self):
        actual = self.build(segments()[:1])
        self.assertIsNone(actual.entries[0].answer)
        self.assertEqual(
            json.loads(actual.json_bytes())["entries"][0]["answer_status"], "NOT_SUPPLIED"
        )

    def test_reordering_retains_source_identity_but_tracks_exact_payload_bytes(self):
        before = self.build()
        after = self.build(list(reversed(segments())))
        self.assertEqual(before.entries[0].source_sha256, after.entries[0].source_sha256)
        self.assertEqual(before.entries[0].external_id, after.entries[0].external_id)
        self.assertNotEqual(before.entries[0].input_sha256, after.entries[0].input_sha256)
        self.assertEqual(before.prepared_bytes(), after.prepared_bytes())
        changed = segments()
        changed[1]["text"] += " نص مختلق إضافي"
        updated = self.build(changed)
        self.assertNotEqual(before.entries[0].external_id, updated.entries[0].external_id)
        self.assertNotEqual(before.rows[0].case.key, updated.rows[0].case.key)

    def test_immutable_snapshot_and_repeat_calls_cannot_contaminate_other_batches(self):
        before = self.build()
        original = before.json_bytes()
        with self.assertRaises(FrozenInstanceError):
            before.entries[0].question.text = "changed"
        decoded = json.loads(original)
        decoded["entries"].clear()
        self.build([dict(segments()[0], source_id="different")])
        self.assertEqual(before.json_bytes(), original)
        self.assertEqual(self.build().json_bytes(), original)

    def test_overlap_duplicate_segment_ambiguous_pair_or_orphan_answer_rejected(self):
        q, a = segments()
        invalid = [
            [q, dict(a, start_ms=1016)],
            [q, dict(a, segment_id="q1")],
            [q, dict(a, kind="question")],
            [a],
            [q, dict(a, pair_id="absent-question")],
            [q, dict(a, source_id="absent-source")],
            [dict(q, source_id=" spaced "), a],
            [dict(q, start_ms=True), a],
            [dict(q, fabricated=False), a],
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                self.build(rows)

    def test_strict_attestation_and_limits_precede_any_queue_output(self):
        from apps.fast8_transcript_queue.services import build_transcript_queue

        for ack in (False, 1, "true", None):
            with self.subTest(ack=ack), self.assertRaises(ValidationError):
                build_transcript_queue(encode(segments()), ".json", synthetic_fixtures_only=ack)
        for raw in (b"[]", b" " * 1000001, b"[NaN]", b'{"items":[],"items":[]}'):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ValidationError):
                build_transcript_queue(raw, ".json", synthetic_fixtures_only=True)
        q = segments()[0]
        with self.assertRaises(ValidationError):
            self.build([dict(q, source_id=f"source-{n}") for n in range(1001)])
        self.assertEqual(
            len(self.build([dict(q, source_id=f"source-{n}") for n in range(1000)]).rows), 1000
        )


if __name__ == "__main__":
    unittest.main()
