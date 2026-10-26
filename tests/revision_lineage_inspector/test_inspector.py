"""Behavior and adversarial checks on invented immutable DTOs, without a database."""

import json
import unittest
from dataclasses import asdict, replace
from datetime import timedelta, timezone, tzinfo
from unittest.mock import patch
from uuid import UUID

from apps.revision_lineage_inspector import (
    LineageInputError,
    inspect_lineage,
    serialize_report,
)
from tools.revision_lineage_inspector.fixtures import synthetic_fixture


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = synthetic_fixture()

    def inspect(self, fixture=None, **changes):
        fixture = fixture or self.fixture
        arguments = {
            "expected_case_id": fixture.expected_case_id,
            "workflow": fixture.workflow,
            "expected_row_id": fixture.expected_row_id,
            "expected_batch_id": fixture.expected_batch_id,
            "source_payload": fixture.source_payload,
            "synthetic_fixtures_only": True,
        }
        arguments.update(changes)
        return inspect_lineage(fixture.record, **arguments)

    def check(self, report, code):
        return next(
            check["status"] for check in report.to_dict()["checks"] if check["code"] == code
        )

    def with_row(self, **changes):
        row = replace(self.fixture.workflow.row, **changes)
        return replace(self.fixture, workflow=replace(self.fixture.workflow, row=row, rows=(row,)))

    def test_valid_evidence_is_consistent_but_does_not_prove_missing_links(self):
        report = self.inspect()
        self.assertEqual(report.to_dict()["status"], "CONSISTENT_WITH_LIMITATIONS")
        for code in (
            "snapshot_event_relationship",
            "draft_workflow_binding",
            "authenticated_attribution",
            "complete_event_history",
            "historical_workflow_references",
        ):
            with self.subTest(code=code):
                self.assertEqual(self.check(report, code), "UNAVAILABLE")

    def test_deterministic_json_and_no_input_mutation_or_text_leak(self):
        before = asdict(self.fixture)
        first = serialize_report(self.inspect())
        second = serialize_report(self.inspect())
        self.assertEqual(first, second)
        self.assertEqual(asdict(self.fixture), before)
        self.assertLess(len(first), 65536)
        for value in (
            self.fixture.record.intake.question,
            self.fixture.record.current.answer,
            self.fixture.record.current.human_editor,
        ):
            self.assertNotIn(value.encode("utf-8"), first)
        self.assertEqual(json.loads(first), self.inspect().to_dict())

    def test_known_corruptions_are_machine_readable_failures(self):
        cases = {
            "revision-order": "revision_order",
            "case-mismatch": "workflow_external_id",
            "source-mismatch": "source_row_attribution",
            "event-order": "event_order",
            "reference-mismatch": "source_reference_attribution",
        }
        for scenario, code in cases.items():
            with self.subTest(scenario=scenario):
                report = self.inspect(synthetic_fixture(scenario))
                self.assertEqual(report.to_dict()["status"], "INCONSISTENT")
                self.assertEqual(self.check(report, code), "FAIL")

    def test_missing_workflow_never_invents_events_or_bindings(self):
        report = self.inspect(synthetic_fixture("missing-workflow"))
        for code in ("workflow_identity", "event_order", "snapshot_event_relationship"):
            self.assertEqual(self.check(report, code), "UNAVAILABLE")

    def test_missing_source_never_claims_attribution_verified(self):
        report = self.inspect(source_payload=None)
        for code in (
            "source_row_attribution",
            "source_reference_attribution",
            "draft_source_attribution",
        ):
            self.assertEqual(self.check(report, code), "UNAVAILABLE")

    def test_guard_requires_literal_true(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=value), self.assertRaises(LineageInputError):
                self.inspect(synthetic_fixtures_only=value)

    def test_case_identity_is_exact_not_normalized(self):
        for identity in (
            self.fixture.expected_case_id.lower(),
            self.fixture.expected_case_id + "x",
        ):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.check(self.inspect(expected_case_id=identity), "case_identity"), "FAIL"
                )

    def test_expected_workflow_ids_require_exact_row_and_batch(self):
        for changes in ({"expected_row_id": UUID(int=999)}, {"expected_batch_id": UUID(int=999)}):
            with self.subTest(changes=changes):
                self.assertEqual(self.check(self.inspect(**changes), "workflow_identity"), "FAIL")
        self.assertEqual(
            self.check(
                self.inspect(expected_row_id=None, expected_batch_id=None), "workflow_identity"
            ),
            "UNAVAILABLE",
        )

    def test_gaps_do_not_imply_missing_events_or_invalid_revisions(self):
        record = replace(
            self.fixture.record,
            history=(
                self.fixture.record.history[0],
                replace(self.fixture.record.history[1], number=4),
            ),
        )
        report = self.inspect(replace(self.fixture, record=record))
        self.assertEqual(self.check(report, "revision_order"), "PASS")
        self.assertEqual(self.check(report, "revision_gaps"), "UNAVAILABLE")

    def test_duplicate_revision_id_fails_contract(self):
        record = replace(
            self.fixture.record,
            history=(
                self.fixture.record.history[0],
                replace(self.fixture.record.history[1], number=1),
            ),
        )
        self.assertEqual(
            self.check(self.inspect(replace(self.fixture, record=record)), "revision_contract"),
            "FAIL",
        )

    def test_boolean_and_out_of_bound_revision_ids_are_rejected(self):
        for number in (True, 0, 1000000):
            record = replace(
                self.fixture.record,
                history=(
                    self.fixture.record.history[0],
                    replace(self.fixture.record.history[1], number=number),
                ),
            )
            with self.subTest(number=number), self.assertRaises(LineageInputError):
                self.inspect(replace(self.fixture, record=record))

    def test_duplicate_event_and_operation_identity_fail_contract(self):
        newest, oldest = self.fixture.workflow.row.events
        for event in (
            replace(newest, id=oldest.id),
            replace(newest, operation_id=oldest.operation_id),
        ):
            with self.subTest(event=event):
                self.assertEqual(
                    self.check(
                        self.inspect(self.with_row(events=(event, oldest))), "workflow_contract"
                    ),
                    "FAIL",
                )

    def test_event_state_contract_and_chain_are_checked(self):
        newest, oldest = self.fixture.workflow.row.events
        bad = replace(newest, to_status="UNREVIEWED")
        self.assertEqual(
            self.check(self.inspect(self.with_row(events=(bad, oldest))), "event_transitions"),
            "FAIL",
        )
        broken = replace(
            newest, action="start_review", from_status="NEEDS_CHANGES", to_status="IN_REVIEW"
        )
        report = self.inspect(self.with_row(events=(broken, oldest), review_status="IN_REVIEW"))
        self.assertEqual(self.check(report, "event_transitions"), "PASS")
        self.assertEqual(self.check(report, "event_chain"), "FAIL")

    def test_event_order_compares_instants_across_offsets(self):
        newest, oldest = self.fixture.workflow.row.events
        newest = replace(
            newest, created_at=newest.created_at.astimezone(timezone(timedelta(hours=-5)))
        )
        oldest = replace(
            oldest, created_at=oldest.created_at.astimezone(timezone(timedelta(hours=3)))
        )
        self.assertEqual(
            self.check(self.inspect(self.with_row(events=(newest, oldest))), "event_order"), "PASS"
        )

    def test_equal_event_instants_use_reader_uuid_tie_break(self):
        newest, oldest = self.fixture.workflow.row.events
        newest = replace(newest, created_at=oldest.created_at)
        self.assertEqual(
            self.check(self.inspect(self.with_row(events=(newest, oldest))), "event_order"), "PASS"
        )
        self.assertEqual(
            self.check(self.inspect(self.with_row(events=(oldest, newest))), "event_order"), "FAIL"
        )

    def test_repeated_local_hour_compares_utc(self):
        class RepeatedHour(tzinfo):
            def utcoffset(self, value):
                return timedelta(hours=1 - value.fold)

            def dst(self, value):
                return timedelta(0)

        newest, oldest = self.fixture.workflow.row.events
        zone = RepeatedHour()
        newest = replace(
            newest, created_at=newest.created_at.replace(hour=9, minute=10, tzinfo=zone, fold=1)
        )
        oldest = replace(
            oldest, created_at=oldest.created_at.replace(hour=9, minute=50, tzinfo=zone, fold=0)
        )
        self.assertEqual(
            self.check(self.inspect(self.with_row(events=(newest, oldest))), "event_order"), "PASS"
        )

    def test_uuid_order_does_not_establish_causality_for_equal_instants(self):
        newest, oldest = self.fixture.workflow.row.events
        newest = replace(newest, id=UUID(int=20), created_at=oldest.created_at)
        oldest = replace(oldest, id=UUID(int=30))
        report = self.inspect(self.with_row(events=(oldest, newest)))
        self.assertEqual(self.check(report, "event_order"), "PASS")
        self.assertEqual(self.check(report, "event_transitions"), "PASS")
        self.assertEqual(self.check(report, "event_chain"), "UNAVAILABLE")
        self.assertEqual(self.check(report, "event_current_state"), "UNAVAILABLE")
        self.assertEqual(report.to_dict()["status"], "CONSISTENT_WITH_LIMITATIONS")

    def test_reference_dto_invariants_checked_even_without_original_payload(self):
        reference = self.fixture.workflow.row.references[0]
        for bad in (
            replace(reference, reference_status="UNKNOWN"),
            replace(reference, citation_text="unverified citation"),
            replace(reference, source_byte_end=reference.source_byte_end + 1),
            replace(reference, source_byte_start=0),
        ):
            with self.subTest(reference=bad):
                report = self.inspect(self.with_row(references=(bad,)), source_payload=None)
                self.assertEqual(self.check(report, "workflow_reference_contract"), "FAIL")
        report = self.inspect(self.with_row(references=(reference, reference)), source_payload=None)
        self.assertEqual(self.check(report, "workflow_reference_contract"), "FAIL")

    def test_source_span_internal_consistency_without_payload(self):
        report = self.inspect(self.with_row(source_byte_end=1), source_payload=None)
        self.assertEqual(self.check(report, "workflow_source_span"), "FAIL")

    def test_empty_source_span_is_inconsistent_even_without_payload(self):
        row = self.fixture.workflow.row
        report = self.inspect(
            self.with_row(original_row="", source_byte_end=row.source_byte_start, references=()),
            source_payload=None,
        )
        self.assertEqual(self.check(report, "workflow_source_span"), "FAIL")
        self.assertEqual(report.to_dict()["status"], "INCONSISTENT")

    def test_report_serialization_validates_bounds_before_encoding(self):
        report = self.inspect()
        for malformed in (
            replace(report, checks=report.checks * 3),
            replace(report, event_count=True),
            replace(report, reference_count=10001),
            replace(report, revision_numbers=(False,)),
        ):
            with self.subTest(report=malformed), self.assertRaises(LineageInputError):
                serialize_report(malformed)

    def test_naive_event_timestamp_rejected(self):
        newest, oldest = self.fixture.workflow.row.events
        newest = replace(newest, created_at=newest.created_at.replace(tzinfo=None))
        with self.assertRaises(LineageInputError):
            self.inspect(self.with_row(events=(newest, oldest)))

    def test_reference_status_never_supplies_historical_resolution(self):
        reference = replace(
            self.fixture.workflow.row.references[0],
            reference_status="VERIFIED",
            citation_text="Synthetic citation label",
        )
        report = self.inspect(self.with_row(references=(reference,)))
        self.assertEqual(self.check(report, "historical_workflow_references"), "UNAVAILABLE")
        self.assertEqual(self.check(report, "snapshot_event_relationship"), "UNAVAILABLE")

    def test_utf8_source_offsets_are_bytes_and_not_character_indices(self):
        reference = self.fixture.workflow.row.references[0]
        self.assertGreater(
            reference.source_byte_start,
            len(self.fixture.source_payload[: reference.source_byte_start].decode("utf-8")),
        )
        changed = replace(reference, source_byte_end=reference.source_byte_end - 1)
        self.assertEqual(
            self.check(
                self.inspect(self.with_row(references=(changed,))), "source_reference_attribution"
            ),
            "FAIL",
        )

    def test_draft_source_text_is_compared_exactly(self):
        intake = replace(
            self.fixture.record.intake, question=self.fixture.record.intake.question.strip()
        )
        report = self.inspect(
            replace(self.fixture, record=replace(self.fixture.record, intake=intake))
        )
        self.assertEqual(self.check(report, "draft_source_attribution"), "FAIL")

    def test_partial_event_window_stays_incomplete(self):
        for truncated in (True, False):
            self.assertEqual(
                self.check(
                    self.inspect(self.with_row(events_truncated=truncated)),
                    "complete_event_history",
                ),
                "UNAVAILABLE",
            )

    def test_shape_and_collection_limits_fail_closed(self):
        for fixture in (
            replace(self.fixture, record=replace(self.fixture.record, history=())),
            replace(
                self.fixture,
                record=replace(self.fixture.record, history=self.fixture.record.history * 51),
            ),
            self.with_row(events=self.fixture.workflow.row.events * 51),
            self.with_row(references=self.fixture.workflow.row.references * 101),
            self.with_row(events_truncated=1),
        ):
            with self.subTest(fixture_type=type(fixture)), self.assertRaises(LineageInputError):
                self.inspect(fixture)

    def test_bad_source_payload_is_rejected_without_leaking_input(self):
        for raw in (b"", b"x" * 1000001):
            with self.subTest(length=len(raw)):
                with self.assertRaises(LineageInputError):
                    self.inspect(source_payload=raw)
        report = self.inspect(source_payload=b"PRIVATE invalid")
        self.assertEqual(self.check(report, "source_contract"), "FAIL")
        self.assertNotIn(b"PRIVATE", serialize_report(report))

    def test_new_snapshot_reference_has_unavailable_source_membership(self):
        current = self.fixture.record.current
        reference = replace(current.reference_links[0], source_id="synthetic-new-reference")
        record = replace(
            self.fixture.record,
            history=(
                self.fixture.record.history[0],
                replace(current, reference_links=(reference,)),
            ),
        )
        report = self.inspect(replace(self.fixture, record=record))
        self.assertEqual(self.check(report, "snapshot_reference_source_membership"), "UNAVAILABLE")
        self.assertEqual(self.check(report, "reference_resolution"), "UNAVAILABLE")

    def test_inspection_never_calls_workflow_reader_or_write_service(self):
        with (
            patch(
                "apps.intake_workflow.review.load_review_worklist",
                side_effect=AssertionError("read"),
            ),
            patch(
                "apps.intake_workflow.review.transition_review", side_effect=AssertionError("write")
            ),
            patch("socket.create_connection", side_effect=AssertionError("network")),
        ):
            self.assertEqual(self.inspect().to_dict()["status"], "CONSISTENT_WITH_LIMITATIONS")


if __name__ == "__main__":
    unittest.main()
