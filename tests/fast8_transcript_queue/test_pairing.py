"""Manual answer-to-question repair, source isolation and portable provenance."""

import io
import json
import unittest
from zipfile import ZipFile

from django.test import SimpleTestCase, override_settings

from apps.fast8_transcript_queue.workbench import services as s
from tests.fast8_transcript_queue import test_workbench_http as web
from tests.fast8_transcript_queue.test_services import encode, segments


def orphan_rows():
    rows = segments()
    rows[1]["pair_id"] = "unpaired-answer"
    return rows


def document(rows):
    return s.open_document(encode(rows), ".json", synthetic_fixtures_only=True)


class PairingServicesTests(unittest.TestCase):
    def test_orphan_answer_becomes_exportable_without_mutating_original_or_answer_text(self):
        before = document(orphan_rows())
        self.assertIsNone(s.review(before)[2])
        with self.assertRaises(s.ValidationError):
            s.export_bundle(before)
        after = s.relink_answer(before, index=1, question_index=0)
        self.assertEqual(after.original, before.original)
        self.assertEqual(after.revision, 1)
        entry = s.review(after)[2].entries[0]
        self.assertEqual(entry.question.text, orphan_rows()[0]["text"])
        self.assertEqual(entry.answer.text, orphan_rows()[1]["text"])
        self.assertEqual(entry.answer.segment_id, orphan_rows()[1]["segment_id"])
        for export in (s.export_bundle, s.checkpoint):
            raw = export(after)
            self.assertEqual(s.restore_bundle(raw, synthetic_fixtures_only=True), after)
            with ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(archive.read("original.json"), before.original)
                manifest = json.loads(archive.read("manifest.json"))
                self.assertTrue(manifest["schema"].endswith(".v2"))
                change = manifest["changes"][0]
                self.assertEqual(change["changed_fields"], ["pair_id"])
                self.assertEqual(change["original_pair_id"], "unpaired-answer")
                self.assertEqual(change["reviewed_pair_id"], "pair-1")
                self.assertFalse(manifest["approval_granted"])

    def test_foreign_source_occupied_ambiguous_and_wrong_role_targets_are_rejected(self):
        rows = orphan_rows()
        rows.append(dict(rows[0], source_id="other-source", segment_id="foreign-question"))
        current = document(rows)
        self.assertEqual([item["index"] for item in s.pairing_options(current, 1)], [0])
        for index, question_index in ((1, 2), (0, 1), (1, True), (-1, 0)):
            with (
                self.subTest(index=index, target=question_index),
                self.assertRaises(s.ValidationError),
            ):
                s.relink_answer(current, index=index, question_index=question_index)
        rows.append(dict(rows[1], segment_id="already-paired-answer", pair_id="pair-1"))
        occupied = document(rows)
        self.assertTrue(s.pairing_options(occupied, 1)[0]["occupied"])
        with self.assertRaises(s.ValidationError):
            s.relink_answer(occupied, index=1, question_index=0)
        rows = orphan_rows() + [dict(orphan_rows()[0], segment_id="duplicate-question")]
        self.assertEqual(s.pairing_options(document(rows), 1), [])

    def test_duplicate_answer_pair_can_be_repaired_to_an_unoccupied_question(self):
        rows = segments()
        rows.extend(
            [
                dict(rows[0], segment_id="q2", pair_id="pair-2", start_ms=2020, end_ms=3020),
                dict(rows[1], segment_id="a2", start_ms=3020, end_ms=4020),
            ]
        )
        before = document(rows)
        self.assertIsNone(s.review(before)[2])
        after = s.relink_answer(before, index=3, question_index=2)
        entries = s.review(after)[2].entries
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry.answer.segment_id for entry in entries], ["a1", "a2"])
        self.assertEqual(s.relink_answer(after, index=3, question_index=2), after)

    def test_pairing_does_not_adjust_timestamps_or_bypass_timing_validation(self):
        rows = orphan_rows()
        rows[0]["start_ms"], rows[0]["end_ms"] = 3000, 4000
        before = document(rows)
        self.assertFalse(s.pairing_options(before, 1)[0]["timing_compatible"])
        linked = s.relink_answer(before, index=1, question_index=0)
        self.assertEqual(s._rows(linked.current, linked.current_suffix)[1]["start_ms"], 1017)
        with self.assertRaises(s.ValidationError):
            s.export_bundle(linked)
        repaired = s.revise(linked, index=1, start_ms=4000, end_ms=5000)
        self.assertIsNotNone(s.review(repaired)[2])

    def test_v2_cannot_be_downgraded_or_change_question_pair_identity(self):
        linked = s.relink_answer(document(orphan_rows()), index=1, question_index=0)
        files = s._read_archive(s.checkpoint(linked))
        manifest = json.loads(files["manifest.json"])
        manifest["schema"] = "fatwa.transcript-workbench.checkpoint.v1"
        files["manifest.json"] = s.pipeline._encoded(manifest)
        with self.assertRaises(s.ValidationError):
            s.restore_bundle(s._archive(files), synthetic_fixtures_only=True)
        rows = s._rows(linked.current, linked.current_suffix)
        rows[0]["pair_id"] = "changed-question-identity"
        forged = s.Document(
            linked.original, linked.original_suffix, s.pipeline._encoded(rows), ".json", 2
        )
        with self.assertRaises(s.ValidationError):
            s.checkpoint(forged)


@override_settings(FATWA_TRANSCRIPT_WORKBENCH_ENABLED=True, SECRET_KEY="synthetic-test-secret")
class PairingHTTPTests(SimpleTestCase):
    setUp = web.WorkbenchHTTPTests.setUp
    browser = web.WorkbenchHTTPTests.browser
    upload = web.WorkbenchHTTPTests.upload
    submit = web.WorkbenchHTTPTests.submit

    def test_browser_repair_preview_comparison_and_question_only_export(self):
        page = self.upload(orphan_rows())
        page = self.submit(page, "select", index=1)
        self.assertContains(page, "ربط الجواب بسؤال من المصدر نفسه")
        self.assertContains(page, 'name="question_index" value="0"')
        self.assertEqual(self.submit(page, "export").status_code, 400)
        linked = self.submit(page, "pair", index=1, question_index=0)
        self.assertEqual(linked.status_code, 200)
        self.assertContains(linked, "unpaired-answer")
        self.assertContains(linked, "الزوج الأصلي")
        exported = self.submit(linked, "export")
        self.assertEqual(exported.status_code, 200)
        with ZipFile(io.BytesIO(exported.content)) as archive:
            queue = json.loads(archive.read("queue.json"))
            self.assertEqual(queue["entries"][0]["answer_status"], "SOURCE_EVIDENCE_ONLY")
            self.assertNotIn(
                orphan_rows()[1]["text"], archive.read("prepared-questions.json").decode()
            )
            self.assertEqual(archive.read("original.json"), encode(orphan_rows()))

    def test_wrong_target_role_or_extra_authority_field_keeps_original_review(self):
        page = self.upload(orphan_rows())
        for fields in (
            dict(index=1, question_index=99),
            dict(index=0, question_index=1),
            dict(index=1, question_index=0, approved="yes"),
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.submit(page, "pair", **fields).status_code, 400)
        self.assertEqual(self.submit(page, "export").status_code, 400)
