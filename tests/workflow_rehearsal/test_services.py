from dataclasses import FrozenInstanceError
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.editorial_workbench.services import build_cases
from apps.intake_workflow.fixtures import ORIGINAL_QUESTION, synthetic_payload
from apps.workflow_rehearsal.services import CASE_KEYS, RehearsalError, build_rehearsal


class RehearsalServiceTests(SimpleTestCase):
    def test_fixed_replay_accepts_only_valid_independent_transitions(self):
        result = build_rehearsal()
        self.assertEqual(result.case.key, "intake-7")
        self.assertEqual(
            [(step.action, step.accepted) for step in result.steps],
            [
                ("complete_review", False),
                ("draft_preparation", True),
                ("published", False),
                ("start_review", True),
                ("request_changes", True),
                ("start_review", True),
                ("complete_review", True),
                ("complete_review", False),
            ],
        )
        self.assertEqual(result.source_record.current.state, "received")
        self.assertEqual(result.projected_record.current.state, "draft_preparation")
        self.assertEqual(result.review_status, "REVIEWED_INTERNAL")
        self.assertEqual(len(result.projected_record.history), 2)
        self.assertTrue(result.projected_record.unpublished)
        self.assertEqual(result.projected_record.current.answer, "")
        for step in result.steps:
            if step.dimension == "review":
                self.assertEqual(step.from_preparation, step.to_preparation)
                self.assertEqual(step.from_revision, step.to_revision)
            else:
                self.assertEqual(step.from_review, step.to_review)
            if not step.accepted:
                self.assertEqual(step.from_preparation, step.to_preparation)
                self.assertEqual(step.from_review, step.to_review)
                self.assertEqual(step.from_revision, step.to_revision)
                self.assertTrue(step.reason)

    def test_replay_preserves_exact_source_reference_identity_and_fixture_digest(self):
        source = next(case for case in build_cases() if case.key == "intake-7")
        result = build_rehearsal()
        self.assertEqual(result.case.question, ORIGINAL_QUESTION)
        self.assertEqual(result.case.raw_source, source.raw_source)
        self.assertEqual(result.case.payload_sha256, sha256(synthetic_payload()).hexdigest())
        self.assertEqual(result.fixture_sha256, result.case.payload_sha256)
        self.assertIs(result.source_record.intake, result.projected_record.intake)
        self.assertIs(
            result.source_record.current.reference_links,
            result.projected_record.current.reference_links,
        )
        self.assertEqual(result.case.references[0]["status"], "verified")
        self.assertEqual(result.case.references[0]["source"], source.references[0]["source"])
        self.assertEqual(
            result.case.references[0]["verified_identity"],
            source.references[0]["verified_identity"],
        )

    def test_every_missing_draft_stays_missing_with_all_attempts_rejected(self):
        for key in (
            "intake-1",
            "intake-2",
            "intake-3",
            "intake-4",
            "intake-5",
            "intake-6",
            "intake-8",
        ):
            with self.subTest(key=key):
                result = build_rehearsal(key)
                self.assertIsNone(result.source_record)
                self.assertIsNone(result.projected_record)
                self.assertEqual(result.review_status, "UNREVIEWED")
                self.assertEqual(result.audit, ())
                self.assertTrue(all(not step.accepted for step in result.steps))
                self.assertTrue(
                    all(step.reason == "rehearsal: no_draft_available" for step in result.steps)
                )

    def test_history_keeps_prior_revisions_and_unresolved_references(self):
        result = build_rehearsal("history")
        self.assertIs(result.source_record, REVISION_HISTORY_RECORD)
        self.assertIs(result.projected_record, result.source_record)
        self.assertEqual([entry.revision.number for entry in result.audit], [1, 2, 4, 7, 9, 11])
        self.assertEqual(result.source_audit, result.audit)
        self.assertEqual(result.case.references[0]["status"], "unresolved")
        self.assertFalse(result.steps[1].accepted)

    def test_revision_audit_records_only_projected_preparation_change(self):
        result = build_rehearsal()
        self.assertEqual(len(result.source_audit), 1)
        self.assertEqual(len(result.audit), 2)
        self.assertIs(result.audit[-1].revision, result.projected_record.current)
        self.assertEqual(result.audit[-1].observed_state_change, ("received", "draft_preparation"))
        self.assertFalse(result.audit[-1].history_entry.content_changed)

    def test_results_are_deeply_immutable_and_repeat_without_shared_state(self):
        result = build_rehearsal()
        with self.assertRaises(FrozenInstanceError):
            result.review_status = "approved"
        with self.assertRaises(FrozenInstanceError):
            result.steps[0].accepted = True
        with self.assertRaises(TypeError):
            result.case.references[0]["status"] = "approved"
        with self.assertRaises(TypeError):
            result.case.references[0]["verified_identity"]["source_id"] = "changed"
        self.assertEqual(result, build_rehearsal())
        self.assertIsNot(result, build_rehearsal())

    def test_only_exact_fixed_selectors_are_accepted_before_fixture_building(self):
        self.assertEqual(
            CASE_KEYS,
            (
                "history",
                "intake-1",
                "intake-2",
                "intake-3",
                "intake-4",
                "intake-5",
                "intake-6",
                "intake-7",
                "intake-8",
            ),
        )
        with patch(
            "apps.workflow_rehearsal.services.build_cases",
            side_effect=AssertionError("invalid selector reached fixtures"),
        ):
            for key in ("", " intake-7", "intake-07", "../history", "wave7-1", None, [], 7):
                with self.subTest(key=key), self.assertRaises(RehearsalError):
                    build_rehearsal(key)
