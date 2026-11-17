"""Focused synthetic import → manual revision → interoperable export tests."""

import io
import json
import unittest
from hashlib import sha256
from zipfile import ZipFile

from apps.fast8_transcript_queue.services import build_transcript_queue
from apps.fast8_transcript_queue.workbench import services as s
from apps.prepared_pipeline import prepare_batch
from tests.fast8_transcript_queue.test_services import encode, segments


class WorkbenchServiceTests(unittest.TestCase):
    def test_formats_roundtrip_original_unicode_and_existing_prepared_contract(self):
        for suffix in (".json", ".csv", ".jsonl"):
            with self.subTest(suffix=suffix):
                raw = encode(segments(), suffix)
                doc = s.open_document(raw, suffix, synthetic_fixtures_only=True)
                bundle = s.export_bundle(doc)
                self.assertEqual(bundle, s.export_bundle(doc))
                with ZipFile(io.BytesIO(bundle)) as archive:
                    self.assertEqual(archive.read("original" + suffix), raw)
                    manifest = json.loads(archive.read("manifest.json"))
                    self.assertEqual(manifest["case_binding"], "NOT_CONNECTED")
                    self.assertFalse(manifest["approval_granted"])
                    for item in manifest["files"]:
                        content = archive.read(item["name"])
                        self.assertEqual(len(content), item["bytes"])
                        self.assertEqual(sha256(content).hexdigest(), item["sha256"])
                    prepared = archive.read("prepared-questions.json")
                    self.assertEqual(
                        json.loads(prepared)["items"][0]["question"], segments()[0]["text"]
                    )
                    self.assertNotIn(segments()[1]["text"], prepared.decode())
                    self.assertFalse(prepare_batch(prepared, synthetic_fixtures_only=True).drafts)
                    queue = json.loads(archive.read("queue.json"))
                    self.assertEqual(queue["entries"][0]["answer"]["text"], segments()[1]["text"])

    def test_overlap_is_reviewable_but_not_exportable_until_manual_repair(self):
        rows = segments()
        rows[1]["start_ms"] = 1000
        doc = s.open_document(encode(rows), ".json", synthetic_fixtures_only=True)
        self.assertFalse(s.review(doc)[1]["cues_allowed"])
        with self.assertRaises(s.ValidationError):
            s.export_bundle(doc)
        fixed = s.revise(doc, index=1, start_ms=1017, end_ms=2019)
        self.assertTrue(s.review(fixed)[1]["cues_allowed"])
        with ZipFile(io.BytesIO(s.export_bundle(fixed))) as archive:
            self.assertEqual(archive.read("original.json"), doc.original)
            self.assertEqual(
                json.loads(archive.read("manifest.json"))["changes"][0]["changed_fields"],
                ["start_ms"],
            )

    def test_timing_edit_preserves_literal_text_and_changes_source_revision_identity(self):
        doc = s.open_document(encode(segments()), ".json", synthetic_fixtures_only=True)
        before = s.review(doc)[2].entries[0]
        changed = s.revise(doc, index=0, start_ms=18, end_ms=1017)
        after = s.review(changed)[2].entries[0]
        self.assertEqual(after.question.text, before.question.text)
        self.assertIn("\r\n", after.question.text)
        self.assertNotEqual(before.external_id, after.external_id)
        self.assertEqual(changed.original, doc.original)
        self.assertEqual(s.revise(changed, index=0, start_ms=18, end_ms=1017), changed)

    def test_explicit_text_replacement_and_reimport_leave_original_in_bundle(self):
        doc = s.open_document(encode(segments()), ".json", synthetic_fixtures_only=True)
        changed = s.revise(
            doc, index=0, start_ms=17, end_ms=1017, replacement_text="  نص اصطناعي بديل\r\n  "
        )
        with ZipFile(io.BytesIO(s.export_bundle(changed))) as archive:
            self.assertEqual(archive.read("original.json"), doc.original)
            reviewed = archive.read("reviewed.json")
            self.assertEqual(
                build_transcript_queue(reviewed, ".json", synthetic_fixtures_only=True)
                .entries[0]
                .question.text,
                "  نص اصطناعي بديل\r\n  ",
            )
            self.assertTrue(json.loads(archive.read("manifest.json"))["manual_editing_performed"])

    def test_missing_answer_remains_explicit_and_is_not_generated(self):
        doc = s.open_document(encode(segments()[:1]), ".json", synthetic_fixtures_only=True)
        with ZipFile(io.BytesIO(s.export_bundle(doc))) as archive:
            entry = json.loads(archive.read("queue.json"))["entries"][0]
            self.assertIsNone(entry["answer"])
            self.assertEqual(entry["answer_status"], "NOT_SUPPLIED")

    def test_rejects_unacknowledged_private_or_oversized_inputs_and_invalid_edits(self):
        raw = encode(segments())
        with self.assertRaises(s.ValidationError):
            s.open_document(raw, ".json")
        for invalid in (b"x" * 1_000_001, b"not-json", raw.replace(b"true", b"false")):
            with self.subTest(size=len(invalid)), self.assertRaises(s.ValidationError):
                s.open_document(invalid, ".json", synthetic_fixtures_only=True)
        doc = s.open_document(raw, ".json", synthetic_fixtures_only=True)
        for kwargs in (
            {"index": -1},
            {"start_ms": True},
            {"end_ms": 0},
            {"replacement_text": ""},
            {"replacement_text": "x" * 20001},
        ):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(s.ValidationError):
                s.revise(doc, **(dict(index=0, start_ms=17, end_ms=1017) | kwargs))
