"""Synthetic examples only: no actual scholarly answer, attribution or source mapping."""

import json
import socket
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from apps.fatwa_drafts.domain import RevisionConflict, SyntheticStage
from apps.fatwa_drafts.intake import (
    SCHEMA,
    IntakeItem,
    ReferenceLink,
    ValidationError,
    parse_intake,
    serialize_intake,
)

HUMAN = {"human_editor": "محرر تجريبي", "editorial_note": "ملاحظة اصطناعية للاختبار"}


def item(ident="STAFF-SYNTHETIC-001"):
    return {
        "external_id": ident,
        "question": "سؤال اصطناعي خاص للاختبار فقط؟",
        "prepared_clip_url": "https://example.invalid/finished.mp4?token=synthetic-secret",
        "staff_notes": "ملاحظة سرية اصطناعية",
        "reference_links": [],
    }


def payload(items=None):
    return json.dumps(
        {"schema": SCHEMA, "items": items if items is not None else [item()]}, ensure_ascii=False
    ).encode("utf-8")


def reference():
    return dict(
        source_namespace="synthetic",
        source_book_id="TEST-BOOK",
        edition_key="TEST-EDITION",
        source_archive_sha256="a" * 64,
        source_input_sha256="b" * 64,
        source_id="TEST-HEADING",
    )


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.stage = SyntheticStage(synthetic_fixtures_only=True)
        self.record = self.stage.ingest(payload(), **HUMAN)[0]
        self.ident = self.record.intake.external_id

    def prepare(self):
        return self.stage.move(self.ident, "draft_preparation", expected_revision=1, **HUMAN)

    def edit(self, revision=2):
        return self.stage.edit(
            self.ident,
            expected_revision=revision,
            title="عنوان اصطناعي",
            answer="نص اختبار بشري؛ ليس فتوى أو إجابة شرعية.",
            reviewer_notes="مراجعة شكلية تجريبية",
            **HUMAN,
        )

    def test_arabic_round_trip(self):
        records = parse_intake(payload())
        self.assertEqual(parse_intake(serialize_intake(records)), records)
        self.assertEqual(records[0].question, item()["question"])
        self.assertEqual(self.record.current.answer, "")
        self.assertTrue(self.record.unpublished)

    def test_history_and_original_preservation(self):
        self.prepare()
        edited = self.edit()
        ready = self.stage.move(self.ident, "ready_for_future_review", expected_revision=3, **HUMAN)
        self.assertEqual(len(ready.history), 4)
        self.assertEqual(ready.intake, self.record.intake)
        self.assertEqual(self.record.current.title, "")
        self.assertEqual(edited.current.human_editor, HUMAN["human_editor"])
        self.assertEqual(ready.history[0].answer, "")
        with self.assertRaises(FrozenInstanceError):
            ready.intake.question = "changed"

    def test_revision_cycle(self):
        self.prepare()
        self.edit()
        self.stage.move(self.ident, "ready_for_future_review", expected_revision=3, **HUMAN)
        self.stage.move(self.ident, "needs_revision", expected_revision=4, **HUMAN)
        self.edit(5)
        self.stage.move(self.ident, "draft_preparation", expected_revision=6, **HUMAN)
        self.assertEqual(self.stage.get(self.ident).current.number, 7)

    def test_conflict_preserves_record(self):
        self.prepare()
        with self.assertRaises(RevisionConflict):
            self.edit(1)
        self.assertEqual(self.stage.get(self.ident).current.number, 2)

    def test_atomic_concurrent_revision_check(self):
        self.prepare()

        def attempt(_):
            try:
                self.edit()
                return "ok"
            except RevisionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), ["conflict", "ok"])

    def test_required_readiness_fields(self):
        self.prepare()
        with self.assertRaisesRegex(ValidationError, "title"):
            self.stage.move(self.ident, "ready_for_future_review", expected_revision=2, **HUMAN)
        self.stage.edit(
            self.ident, expected_revision=2, title="عنوان", answer="", reviewer_notes="", **HUMAN
        )
        with self.assertRaisesRegex(ValidationError, "human_answer"):
            self.stage.move(self.ident, "ready_for_future_review", expected_revision=3, **HUMAN)

    def test_prohibited_transitions(self):
        for state in ("approved", "published", "ready_for_future_review", "needs_revision"):
            with self.subTest(state=state), self.assertRaises(ValidationError):
                self.stage.move(self.ident, state, expected_revision=1, **HUMAN)
        with self.assertRaises(ValidationError):
            self.edit(1)

    def test_duplicate_and_atomic_ingest(self):
        with self.assertRaises(ValidationError):
            self.stage.ingest(payload([item("NEW"), item()]), **HUMAN)
        with self.assertRaises(ValidationError):
            self.stage.get("NEW")
        with self.assertRaises(ValidationError):
            parse_intake(payload([item(), item()]))

    def test_redacted_deterministic_preview(self):
        self.prepare()
        self.edit()
        preview = self.stage.preview()
        for secret in (
            self.ident,
            item()["question"],
            item()["prepared_clip_url"],
            item()["staff_notes"],
            HUMAN["human_editor"],
            "عنوان اصطناعي",
        ):
            self.assertNotIn(secret.encode(), preview)
        self.assertIn(b"missing_manual_references", preview)
        self.assertEqual(preview, self.stage.preview())
        self.assertIn(
            item()["question"].encode(), self.stage.preview(include_synthetic_content=True)
        )
        self.assertEqual(self.stage.get(self.ident).current.number, 3)

    def test_no_network_database_or_files(self):
        import sys

        before = set(sys.modules)
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network")),
            patch("builtins.open", side_effect=AssertionError("file")),
        ):
            stage = SyntheticStage(synthetic_fixtures_only=True)
            stage.ingest(payload(), **HUMAN)
            stage.preview()
        self.assertFalse(
            any(name.startswith(("django.db", "psycopg")) for name in set(sys.modules) - before)
        )

    def test_fixture_guard(self):
        with self.assertRaises(ValidationError):
            SyntheticStage()

    def test_human_metadata_required(self):
        with self.assertRaises(ValidationError):
            self.stage.move(
                self.ident,
                "draft_preparation",
                expected_revision=1,
                human_editor="",
                editorial_note="",
            )


class IntakeTests(unittest.TestCase):
    def test_exact_manual_reference_preserved(self):
        raw = item()
        raw["reference_links"] = [reference()]
        parsed = parse_intake(payload([raw]))
        self.assertEqual(parsed[0].reference_links, (ReferenceLink(**reference()),))
        self.assertEqual(parse_intake(serialize_intake(parsed)), parsed)

    def test_missing_ambiguous_or_duplicate_references(self):
        for refs in (
            [{"source_id": "1"}],
            [reference(), reference()],
            None,
            [{**reference(), "edition_key": ""}],
            [{**reference(), "source_archive_sha256": "bad"}],
            [{**reference(), "inferred": True}],
        ):
            with self.subTest(refs=refs), self.assertRaises(ValidationError):
                parse_intake(payload([{**item(), "reference_links": refs}]))

    def test_missing_required_fields_and_links(self):
        for field in ("external_id", "question", "prepared_clip_url"):
            raw = item()
            del raw[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse_intake(payload([raw]))
        for url in (
            "",
            "http://example.invalid/a",
            "file:///tmp/a",
            "https://x/a#frag",
            "https://user:pass@example.invalid/a",
            "https://x:bad/a",
            "https://x/a b",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                parse_intake(payload([{**item(), "prepared_clip_url": url}]))

    def test_bad_json_and_utf8(self):
        for data in (
            b"\xff",
            b"\xef\xbb\xbf{}",
            b'{"schema":1,"schema":2}',
            b"[]",
            b"NaN",
            b"x" * 1_000_001,
            b'{"schema":"x","items":[]}',
            b'"\\ud800"',
        ):
            with self.subTest(size=len(data)), self.assertRaises(ValidationError):
                parse_intake(data)
        data = json.dumps({"schema": SCHEMA, "items": [{**item(), "question": "\ud800"}]}).encode()
        with self.assertRaises(ValidationError):
            parse_intake(data)

    def test_types_bounds_and_unknown_fields(self):
        for change in (
            {"question": 1},
            {"external_id": " id "},
            {"question": " "},
            {"staff_notes": "\x00"},
            {"answer": "automatic"},
            {"reference_links": {}},
            {"question": "a" * 20001},
        ):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                parse_intake(payload([{**item(), **change}]))
        with self.assertRaises(ValidationError):
            parse_intake(payload([]))
        with self.assertRaises(ValidationError):
            IntakeItem("x", "q", "https://example.invalid", reference_links=[])


if __name__ == "__main__":
    unittest.main()
