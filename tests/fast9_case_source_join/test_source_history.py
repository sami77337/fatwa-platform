from dataclasses import FrozenInstanceError, replace
from unittest import TestCase

from apps.fast9_case_source_join import source_history as sh


class SourceHistoryTests(TestCase):
    def setUp(self):
        self.original = sh.source_receipt("intake-1")
        self.edit = replace(
            self.original,
            event_id="edit-1",
            kind="corrected",
            prior_event_id=self.original.event_id,
            body_utf8=sh.CORRECTION_BODIES[0],
        )
        self.deletion = replace(
            self.edit, event_id="delete-1", kind="deleted", prior_event_id="edit-1", body_utf8=None
        )

    def replay(self, *events):
        return sh.replay_source_history(events, synthetic_fixtures_only=True)

    def test_receipt_preserves_question_and_independent_original_json_row_hash(self):
        self.assertEqual(self.original.body_utf8, "  سُؤَالٌ اصطناعي\tبِعلاماته\nوسطره  ".encode())
        self.assertEqual(
            self.original.row_sha256,
            "9997733aafa7ef2daf20e944fecf31a5057d4c8d48b0575ecdc1fc26b7c96a09",
        )
        duplicate_id = sh.source_receipt("intake-4")
        same_question = sh.source_receipt("intake-7")
        self.assertNotEqual(duplicate_id.row_sha256, self.original.row_sha256)
        self.assertEqual(same_question.body_utf8, self.original.body_utf8)
        self.assertNotEqual(same_question.row_sha256, self.original.row_sha256)

    def test_correction_and_deletion_keep_historical_bytes_even_after_retries(self):
        history = self.replay(self.original, self.edit, self.original, self.deletion, self.edit)
        self.assertEqual(history, (self.original, self.edit, self.deletion))
        self.assertNotEqual(history[0].body_utf8, history[1].body_utf8)
        self.assertIsNone(history[-1].body_utf8)
        with self.assertRaises(FrozenInstanceError):
            history[0].body_utf8 = b""

    def test_exact_retry_dedupes_but_conflicting_reuse_rejects(self):
        self.assertEqual(self.replay(self.original, self.original), (self.original,))
        for conflict in (
            replace(self.edit, body_utf8=sh.CORRECTION_BODIES[1]),
            replace(self.edit, prior_event_id="unrelated"),
        ):
            with self.subTest(conflict=conflict), self.assertRaises(ValueError):
                self.replay(self.original, self.edit, conflict)

    def test_fabricated_or_cross_case_receipts_and_updates_reject(self):
        for field in ("channel", "account", "conversation", "source_ref", "case_key", "row_sha256"):
            for event in (self.original, self.edit):
                forged = replace(event, **{field: "intake-7"})
                sequence = (forged,) if event is self.original else (self.original, forged)
                with self.subTest(field=field, kind=event.kind), self.assertRaises(ValueError):
                    self.replay(*sequence)
        for key in ("intake-4", "intake-7"):
            other = sh.source_receipt(key)
            crossed = replace(
                other,
                event_id="edit-1",
                kind="corrected",
                prior_event_id=self.original.event_id,
                body_utf8=self.edit.body_utf8,
            )
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.replay(self.original, crossed)

    def test_stale_parent_missing_root_late_edit_and_non_fixture_body_reject(self):
        bad_streams = (
            (),
            (self.edit,),
            (replace(self.original, body_utf8=self.edit.body_utf8),),
            (self.original, self.edit, replace(self.edit, event_id="fork")),
            (
                self.original,
                self.edit,
                self.deletion,
                replace(self.edit, event_id="late", prior_event_id="delete-1"),
            ),
            (self.original, replace(self.edit, body_utf8=b"arbitrary input")),
            (self.original, replace(self.edit, body_utf8=None)),
            (self.original, replace(self.edit, kind="deleted")),
            (self.original, replace(self.edit, body_utf8=bytearray(self.edit.body_utf8))),
            (self.original, replace(self.edit, event_id="")),
            (self.original, replace(self.edit, event_id=True)),
        )
        for stream in bad_streams:
            with self.subTest(stream=stream), self.assertRaises(ValueError):
                self.replay(*stream)

    def test_distinct_same_content_events_remain_distinct(self):
        echo = replace(self.edit, event_id="edit-2", prior_event_id=self.edit.event_id)
        self.assertEqual(
            self.replay(self.original, self.edit, echo), (self.original, self.edit, echo)
        )

    def test_requires_literal_opt_in_and_known_case(self):
        for flag in (False, 1, None):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                sh.replay_source_history([self.original], synthetic_fixtures_only=flag)
        for case_key in ("unknown", "intake-01", None):
            with self.subTest(case_key=case_key), self.assertRaises(ValueError):
                sh.source_receipt(case_key)
