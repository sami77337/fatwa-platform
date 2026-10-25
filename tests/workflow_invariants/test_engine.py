import copy
import json
import unittest
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_workbench.services import build_cases
from apps.fatwa_drafts.domain import transition
from apps.intake_workflow.contracts import REVIEW_TRANSITIONS
from apps.intake_workflow.fixtures import synthetic_payload
from apps.revision_core.revision_history import HistoryDataError
from apps.workflow_invariants.engine import (
    ReplayError,
    canonical_bytes,
    make_event,
    replay,
    scenario,
)
from apps.workflow_rehearsal.services import build_rehearsal


class ReplayTests(unittest.TestCase):
    def test_rehearsal_parity_and_deterministic_complete_snapshots(self):
        request = scenario("rehearsal")
        original = copy.deepcopy(request)
        result = replay(request)
        existing = build_rehearsal()
        self.assertEqual(request, original)
        self.assertEqual(canonical_bytes(result), canonical_bytes(replay(request)))
        self.assertEqual(
            [s["accepted"] for s in result["steps"]], [s.accepted for s in existing.steps]
        )
        self.assertEqual(result["final"]["review"], existing.review_status)
        self.assertEqual(
            result["final"]["record"]["history"][-1]["state"],
            existing.projected_record.current.state,
        )
        self.assertEqual(result["owner_transitions"], "NOT_SUPPLIED")
        self.assertTrue(result["invariants_passed"])
        for step in result["steps"]:
            self.assertEqual(step["state_changed"], step["before"] != step["after"])
            if not step["accepted"]:
                self.assertEqual(step["before"], step["after"])
                self.assertEqual(step["changed_paths"], [])
        self.assertIn("س", canonical_bytes(result).decode())

    def test_all_actual_edges_and_original_history_gaps(self):
        edges = set()
        for name in ("rehearsal", "preparation"):
            result = replay(scenario(name))
            for step in result["steps"]:
                if step["accepted"] and step["disposition"] == "APPLIED":
                    event = step["event"]
                    if event["dimension"] == "preparation":
                        before = step["before"]["record"]["history"][-1]["state"]
                        after = step["after"]["record"]["history"][-1]["state"]
                        edges.add((before, after))
        self.assertEqual(
            edges,
            {
                ("received", "draft_preparation"),
                ("draft_preparation", "needs_revision"),
                ("needs_revision", "draft_preparation"),
                ("draft_preparation", "ready_for_future_review"),
                ("ready_for_future_review", "needs_revision"),
            },
        )
        result = replay(scenario("preparation"))
        self.assertEqual(
            [r["number"] for r in result["initial"]["record"]["history"]], [1, 2, 4, 7, 9, 11]
        )
        self.assertEqual(result["final"]["record"]["intake"], result["initial"]["record"]["intake"])
        reviews = replay(scenario("rehearsal"))["steps"]
        observed = {
            (s["before"]["review"], s["event"]["action"]): s["after"]["review"]
            for s in reviews
            if s["accepted"] and s["event"]["dimension"] == "review"
        }
        self.assertEqual(observed, dict(REVIEW_TRANSITIONS))

    def test_retries_preserve_current_state_and_conflicts_reject(self):
        request = scenario("rehearsal")
        request["events"].append(copy.deepcopy(request["events"][1]))
        conflict = copy.deepcopy(request["events"][1])
        conflict["action"] = "needs_revision"
        request["events"].append(conflict)
        request["events"].append(copy.deepcopy(request["events"][0]))
        result = replay(request)
        retry, conflict_result, rejected_retry = result["steps"][-3:]
        self.assertTrue(retry["accepted"])
        self.assertEqual(retry["disposition"], "REPLAY")
        self.assertEqual(retry["original_ordinal"], 2)
        self.assertEqual(retry["before"], retry["after"])
        self.assertEqual(conflict_result["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertFalse(rejected_retry["accepted"])
        self.assertEqual(rejected_retry["disposition"], "REPLAY")

    def test_invalid_out_of_order_source_and_stale_state_are_atomic(self):
        for field, value, reason in (
            ("sequence", 2, "event: out_of_order"),
            ("sequence", True, "event: invalid_schema"),
            ("source_identity", {}, "event: source_identity_mismatch"),
            ("expected_state", {}, "event: state_before_mismatch"),
            ("dimension", "owner", "event: invalid_schema"),
            ("action", "approved", "review: transition_not_allowed"),
        ):
            with self.subTest(field=field, value=value):
                request = scenario("rehearsal")
                request["events"] = request["events"][:1]
                request["events"][0][field] = value
                result = replay(request)
                self.assertEqual(result["steps"][0]["reason"], reason)
                self.assertEqual(result["initial"], result["final"])

    def test_no_draft_is_created_for_blocked_duplicate_source_row(self):
        request = scenario("blocked")
        result = replay(request)
        self.assertIsNone(result["final"]["record"])
        self.assertTrue(all(s["reason"] == "event: no_draft_available" for s in result["steps"]))

    def test_domain_contract_is_used_without_text_or_identity_changes(self):
        request = scenario("preparation")
        record = build_rehearsal("history").source_record
        result = replay(request)
        for step in result["steps"]:
            record = transition(
                record,
                step["event"]["action"],
                expected_revision=record.current.number,
                human_editor="محاكاة تقنية اصطناعية",
                editorial_note="إسقاط في الذاكرة فقط؛ لا اعتماد أو نشر.",
            )
            self.assertEqual(
                step["after"]["record"]["history"][-1]["number"], record.current.number
            )
            self.assertEqual(
                step["after"]["record"]["history"][-1]["answer"], record.current.answer
            )

    def test_envelope_requires_explicit_synthetic_scope_and_bounded_events(self):
        for field, value in (
            ("synthetic_fixtures_only", False),
            ("case_key", "../private"),
            ("events", [None] * 65),
            ("unexpected", True),
        ):
            request = scenario("rehearsal")
            request[field] = value
            with self.subTest(field=field), self.assertRaises(ReplayError):
                replay(request)

    def test_full_before_hash_detects_stale_review_and_make_event_is_detached(self):
        request = scenario("rehearsal")
        event = make_event("intake-7", 1, "review", "start_review")
        request["events"] = [event, dict(event, event_id="next", sequence=2)]
        result = replay(request)
        self.assertEqual(result["steps"][1]["reason"], "event: state_before_mismatch")
        self.assertEqual(json.loads(canonical_bytes(result)), result)

    def test_exact_original_row_and_all_reference_identity_fields_are_retained(self):
        request = scenario("rehearsal")
        result = replay(request)
        case = next(c for c in build_cases() if c.key == "intake-7")
        self.assertEqual(result["source"]["raw_text"], case.raw_source)
        self.assertEqual(result["source"]["references"], list(case.references))
        self.assertEqual(
            result["source_identity"]["payload_sha256"], sha256(synthetic_payload()).hexdigest()
        )
        self.assertEqual(
            synthetic_payload()[case.source_start : case.source_end],
            result["source"]["raw_text"].encode(),
        )
        for field in case.references[0]["verified_identity"]:
            changed = copy.deepcopy(request)
            identity = changed["events"][0]["source_identity"]["reference_identities"][0]
            identity["verified_identity"][field] = "changed"
            self.assertEqual(
                replay(changed)["steps"][0]["reason"], "event: source_identity_mismatch"
            )

    def test_no_io_and_no_mutation_or_shared_result_aliases(self):
        request = scenario("preparation")
        with (
            patch("builtins.open", side_effect=AssertionError("filesystem")),
            patch("socket.socket", side_effect=AssertionError("network")),
        ):
            result = replay(request)
        result["gates"]["Gate B"] = "changed"
        result["steps"][0]["event"]["action"] = "changed"
        result["final"]["record"]["intake"]["question"] = "changed"
        fresh = replay(request)
        self.assertEqual(fresh["gates"]["Gate B"], "NOT_PASSED")
        self.assertNotEqual(fresh["final"]["record"]["intake"]["question"], "changed")

    def test_contract_disagreement_never_reports_success(self):
        request = scenario("preparation")

        def bad_transition(record, *args, **kwargs):
            return replace(record, intake=replace(record.intake, question="changed"))

        with patch("apps.workflow_invariants.engine.transition", side_effect=bad_transition):
            with self.assertRaisesRegex(ReplayError, "invariant: contract_result_mismatch"):
                replay(request)
        review = scenario("rehearsal")
        review["events"] = [make_event("intake-7", 1, "review", "start_review")]
        from apps.intake_workflow.contracts import ReviewStatus

        with patch(
            "apps.workflow_invariants.engine.next_review_status",
            return_value=ReviewStatus.REVIEWED_INTERNAL,
        ):
            with self.assertRaisesRegex(ReplayError, "invariant: contract_result_mismatch"):
                replay(review)

    def test_invalid_initial_and_resulting_history_are_invariant_failures(self):
        request = scenario("preparation")
        with patch(
            "apps.workflow_invariants.engine.build_history",
            side_effect=HistoryDataError("invalid_history_content"),
        ):
            with self.assertRaisesRegex(ReplayError, "invariant: invalid_history"):
                replay(request)

        def invalid_history(record, *args, **kwargs):
            candidate = transition(record, *args, **kwargs)
            return replace(
                candidate, history=(*candidate.history[:-1], replace(candidate.current, action=""))
            )

        with patch("apps.workflow_invariants.engine.transition", side_effect=invalid_history):
            with self.assertRaisesRegex(ReplayError, "invariant: invalid_history"):
                replay(request)

    def test_all_invalid_events_allow_the_next_valid_event_to_be_evaluated(self):
        event = make_event("intake-7", 1, "preparation", "draft_preparation")
        for invalid in (
            None,
            [],
            "x",
            {},
            dict(event, sequence=2),
            dict(event, source_identity={}),
        ):
            request = scenario("rehearsal")
            request["events"] = [invalid, event]
            result = replay(request)
            self.assertFalse(result["steps"][0]["accepted"])
            self.assertTrue(result["steps"][1]["accepted"])
            self.assertEqual(result["next_sequence"], 2)

    def test_duplicate_external_ids_cannot_substitute_row_identity(self):
        first = make_event("intake-1", 1, "review", "start_review")
        fourth = make_event("intake-4", 1, "review", "start_review")
        self.assertEqual(
            first["source_identity"]["external_id"], fourth["source_identity"]["external_id"]
        )
        request = scenario("blocked")
        request["events"] = [fourth]
        self.assertEqual(replay(request)["steps"][0]["reason"], "event: source_identity_mismatch")
