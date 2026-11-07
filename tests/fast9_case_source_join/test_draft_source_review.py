"""The fabricated intake snapshot can warn about changes; it cannot approve a reply."""

import json
import unittest
from dataclasses import asdict, replace
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_workbench.services import build_cases
from apps.fast9_case_source_join import draft_source_review as review
from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt


class DraftSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.start = source_receipt("intake-7")
        self.edit = replace(
            self.start,
            event_id="edit-1",
            prior_event_id=self.start.event_id,
            kind="corrected",
            body_utf8=CORRECTION_BODIES[0],
        )
        self.delete = replace(
            self.edit,
            event_id="delete-1",
            prior_event_id=self.edit.event_id,
            kind="deleted",
            body_utf8=None,
        )

    def observe(self, *events, key="intake-7", revision=1):
        return review.inspect_draft_source(key, revision, events, synthetic_fixtures_only=True)

    def test_baseline_matches_native_revision_and_exact_source(self):
        case = next(c for c in build_cases() if c.key == "intake-7")
        baseline = self.observe(self.start)
        revision_bytes = json.dumps(
            asdict(case.record.current),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(baseline.draft_revision_sha256, sha256(revision_bytes).hexdigest())
        self.assertEqual(baseline.original_row_sha256, sha256(case.raw_source.encode()).hexdigest())
        self.assertEqual(
            baseline.original_question_sha256,
            sha256(case.record.intake.question.encode()).hexdigest(),
        )
        self.assertEqual(baseline.last_supplied_question_sha256, baseline.original_question_sha256)
        self.assertEqual(
            (baseline.changed_event_ids, baseline.status), ((), "SOURCE_TEXT_UNCHANGED")
        )

    def test_edits_warn_and_reopening_or_retry_cannot_clear_warning(self):
        result = self.observe(self.start, self.edit)
        self.assertEqual(result.status, "SOURCE_TEXT_CHANGED_REVIEW_NEEDED")
        self.assertEqual(result.changed_event_ids, (self.edit.event_id,))
        self.assertNotEqual(result.last_supplied_question_sha256, result.original_question_sha256)
        self.assertEqual(self.observe(self.start, self.edit, self.edit), result)
        self.assertEqual(self.observe(self.start, self.edit), result)
        same_text = replace(self.edit, event_id="edit-2", prior_event_id=self.edit.event_id)
        self.assertEqual(
            self.observe(self.start, self.edit, same_text),
            replace(result, last_supplied_event_id="edit-2"),
        )

    def test_restored_text_keeps_intervening_change_visible(self):
        restored = replace(
            self.edit,
            event_id="restore-1",
            prior_event_id=self.edit.event_id,
            body_utf8=self.start.body_utf8,
        )
        observation = self.observe(self.start, self.edit, restored, self.start)
        self.assertEqual(
            observation.last_supplied_question_sha256,
            observation.original_question_sha256,
        )
        self.assertEqual(observation.status, "SOURCE_TEXT_CHANGED_REVIEW_NEEDED")
        self.assertEqual(observation.changed_event_ids, (self.edit.event_id, restored.event_id))

    def test_native_snapshot_must_match_initial_source_and_exist(self):
        case = next(c for c in build_cases() if c.key == self.start.case_key)
        for invalid in (
            replace(case, raw_source=case.raw_source + " "),
            replace(case, record=None),
        ):
            with (
                self.subTest(source=invalid.raw_source),
                patch.object(review, "build_cases", return_value=(invalid,)),
            ):
                with self.assertRaises(ValueError):
                    self.observe(self.start)

    def test_tombstone_retains_original_but_no_current_question(self):
        result = self.observe(self.start, self.edit, self.delete)
        self.assertIsNone(result.last_supplied_question_sha256)
        self.assertEqual(result.status, "SOURCE_DELETED_REVIEW_NEEDED")
        self.assertEqual(result.changed_event_ids, (self.edit.event_id, self.delete.event_id))
        self.assertEqual(
            result.original_question_sha256,
            self.observe(self.start).original_question_sha256,
        )

    def test_same_question_or_external_id_cannot_bridge_cases(self):
        same_question = source_receipt("intake-1")
        same_external_id = source_receipt("intake-4")
        self.assertEqual(same_question.body_utf8, self.start.body_utf8)
        for event, key in ((same_question, "intake-7"), (same_external_id, "intake-1")):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "source_case_mismatch"),
            ):
                self.observe(event, key=key)

    def test_revision_and_opt_in_are_exact(self):
        for revision in (True, 1.0, "1", 0, 2):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.observe(self.start, revision=revision)
        with self.assertRaises(ValueError):
            review.inspect_draft_source("intake-7", 1, (self.start,))
