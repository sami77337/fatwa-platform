"""Exact source revision identities across the actual transcript/prepared boundary."""

import codecs
import hashlib
import json
import unittest

from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from apps.transcript_pipeline import segment_file
from tools.fast8_ingest_adversarial.fixtures import FORMATS, ORIGINAL, encode, segment_row


class TranscriptRevisionTests(unittest.TestCase):
    def process(self, rows, suffix=".json"):
        return segment_file(encode(rows, suffix), suffix, synthetic_fixtures_only=True)

    def test_format_and_bom_change_input_hash_but_keep_source_revision_and_export(self):
        rows = [segment_row()]
        baseline = self.process(rows)
        original = json.loads(baseline.json_bytes())
        hashes = set()
        for suffix in FORMATS:
            for bom in (False, True):
                with self.subTest(format=suffix, bom=bom):
                    raw = encode(rows, suffix, bom=bom)
                    batch = segment_file(raw, suffix, synthetic_fixtures_only=True)
                    report = json.loads(batch.json_bytes())
                    hashes.add(report["input_sha256"])
                    self.assertEqual(report["input_sha256"], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(report["sources"], original["sources"])
                    self.assertEqual(report["segments"], rows)
                    self.assertEqual(batch.prepared_bytes(), baseline.prepared_bytes())
                    self.assertEqual(
                        report["preparation"]["export_sha256"],
                        hashlib.sha256(batch.prepared_bytes()).hexdigest(),
                    )
        self.assertEqual(len(hashes), 6)

    def test_revision_changes_invalidate_all_same_source_pair_ids_only(self):
        rows = [
            segment_row(),
            segment_row(segment_id="segment-2", pair_id="pair-2", start_ms=456, end_ms=789),
            segment_row(source_id="SYN-other"),
        ]
        baseline = json.loads(self.process(rows).json_bytes())
        old_ids = {(p["source_id"], p["pair_id"]): p["external_id"] for p in baseline["pairs"]}
        for changes in (
            {"text": ORIGINAL + " "},
            {"end_ms": 455},
            {"provenance": "FAST8-fabricated-revision-2"},
        ):
            with self.subTest(changes=changes):
                edited = [{**rows[0], **changes}, *rows[1:]]
                batch = self.process(edited)
                report = json.loads(batch.json_bytes())
                self.assertEqual(report["segments"], edited)
                for pair in report["pairs"]:
                    key = (pair["source_id"], pair["pair_id"])
                    if pair["source_id"] == "SYN-other":
                        self.assertEqual(pair["external_id"], old_ids[key])
                    else:
                        self.assertNotEqual(pair["external_id"], old_ids[key])
                self.assertNotEqual(
                    report["preparation"]["export_sha256"], baseline["preparation"]["export_sha256"]
                )

    def test_repeated_source_is_valid_but_duplicate_source_segment_pair_fails(self):
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                first = segment_row()
                second = segment_row(
                    segment_id="segment-2", pair_id="pair-2", start_ms=456, end_ms=789
                )
                good = json.loads(self.process([first, second], suffix).json_bytes())
                self.assertEqual(good["sources"][0]["segment_count"], 2)
                self.assertEqual(len(good["pairs"]), 2)
                # Different interval/pair avoids an accidental overlap/ambiguous-pair oracle.
                second["segment_id"] = first["segment_id"]
                with self.assertRaisesRegex(ValidationError, "^segments.2: duplicate_segment_id$"):
                    self.process([first, second], suffix)

    def test_export_reaches_preparation_without_invented_media_answers_or_approval(self):
        batch = self.process([segment_row()], ".csv")
        export = batch.prepared_bytes()
        self.assertFalse(export.startswith(codecs.BOM_UTF8))
        item = json.loads(export)["items"][0]
        self.assertEqual(item["question"].encode(), ORIGINAL.encode())
        self.assertEqual(item["prepared_clip_url"], "")
        self.assertEqual(item["reference_links"], [])
        self.assertNotIn("answer", item)
        prepared = prepare_batch(export, synthetic_fixtures_only=True)
        self.assertEqual(prepared.drafts, ())
        self.assertEqual(prepared.report["input_sha256"], hashlib.sha256(export).hexdigest())
        self.assertEqual(prepared.report["items"][0]["original"], item)
        self.assertIn("needs-editor-review", prepared.report["items"][0]["statuses"])
        self.assertFalse(json.loads(batch.json_bytes())["publication_allowed"])


if __name__ == "__main__":
    unittest.main()
