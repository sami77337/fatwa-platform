import copy
import unittest
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_workbench.batch_fixtures import synthetic_inputs
from apps.editorial_workbench.services import build_prepared_workbench
from apps.fast8_prepared_review import services as bridge
from apps.workflow_invariants.engine import canonical_bytes, state_token
from apps.workflow_rehearsal.services import build_prepared_rehearsal

KEY = "batch-synthetic-csv-1"


def request(key=KEY, dimension="preparation", action="draft_preparation"):
    view = bridge.inspect_case(key, synthetic_fixtures_only=True)
    return {
        "schema": bridge.SCHEMA,
        "synthetic_fixtures_only": True,
        "case_key": key,
        "commands": [
            {
                "dimension": dimension,
                "action": action,
                "source_identity": view["source_identity"],
                "expected_state": state_token(view["initial"]),
            }
        ],
    }


class BridgeTests(unittest.TestCase):
    def test_real_preparation_and_review_contract_parity(self):
        expected = build_prepared_rehearsal(KEY, synthetic_fixtures_only=True)
        result = bridge.project(bridge.scenario(KEY, synthetic_fixtures_only=True))
        steps = result["steps"][: len(expected.steps)]
        self.assertEqual([s["accepted"] for s in steps], [s.accepted for s in expected.steps])
        self.assertEqual(steps[-1]["after"]["review"], expected.review_status)
        self.assertEqual(steps[-1]["after"]["record"]["history"][-1]["number"], 2)
        self.assertEqual(result["final"]["record"]["history"][-1]["answer"], "")
        self.assertEqual(result["joins"]["preparation_to_review"]["status"], "NOT_CONNECTED")
        self.assertEqual(result["joins"]["reference_to_wave7"]["status"], "NOT_CONNECTED")

    def test_every_existing_row_retains_missing_drafts_and_identity(self):
        for case in build_prepared_workbench().cases:
            with self.subTest(key=case.key):
                result = bridge.project(bridge.scenario(case.key, synthetic_fixtures_only=True))
                self.assertEqual(result["source_identity"]["batch_id"], case.batch_id)
                self.assertEqual(result["source_identity"]["row_ordinal"], case.row_ordinal)
                if case.record is None:
                    self.assertIsNone(result["final"]["record"])
                    self.assertFalse(any(s["accepted"] for s in result["steps"]))
                for step in result["steps"]:
                    if not step["accepted"]:
                        self.assertEqual(step["before"], step["after"])
                        self.assertEqual(step["before_sha256"], step["after_sha256"])

    def test_exact_source_fingerprint_and_unmodified_unicode(self):
        result = bridge.project(request())
        original = build_prepared_workbench().cases[0]
        raw = synthetic_inputs()[0].raw
        self.assertEqual(result["source_identity"]["payload_sha256"], sha256(raw).hexdigest())
        self.assertEqual(result["source"]["batch_raw_text"].encode("utf-8"), raw)
        self.assertEqual(result["source"]["row_kind"], "serialized_parsed_fields")
        self.assertIsNone(result["source"]["row_start"])
        self.assertIsNone(result["source"]["row_end"])
        for state in (result["initial"], result["final"]):
            self.assertEqual(state["record"]["intake"]["question"], original.question)
            self.assertIn("\r\n", state["record"]["intake"]["question"])
            self.assertIn("e\u0301", state["record"]["intake"]["question"])
        self.assertEqual(
            result["initial"]["record"]["history"], result["final"]["record"]["history"][:-1]
        )

    def test_all_identity_fields_are_required_and_exact(self):
        identity = request()["commands"][0]["source_identity"]
        for field in identity:
            for mode in ("missing", "changed"):
                with self.subTest(field=field, mode=mode):
                    req = request()
                    token = req["commands"][0]["source_identity"]
                    if mode == "missing":
                        del token[field]
                    else:
                        token[field] = "wrong-synthetic-value"
                    step = bridge.project(req)["steps"][0]
                    self.assertEqual(step["reason"], "bridge: source_identity_mismatch")
                    self.assertFalse(step["accepted"])

    def test_state_tokens_reject_stale_type_aliases_and_hash_changes(self):
        for field, value in (
            ("revision", True),
            ("revision", 99),
            ("preparation", "draft_preparation"),
            ("review", "IN_REVIEW"),
            ("state_sha256", "0" * 64),
        ):
            with self.subTest(field=field, value=value):
                req = request()
                req["commands"][0]["expected_state"][field] = value
                step = bridge.project(req)["steps"][0]
                self.assertEqual(step["reason"], "bridge: state_snapshot_mismatch")
                self.assertEqual(step["before"], step["after"])
        req = request()
        req["commands"].append(copy.deepcopy(req["commands"][0]))
        result = bridge.project(req)
        self.assertTrue(result["steps"][0]["accepted"])
        self.assertFalse(result["steps"][1]["accepted"])

    def test_no_external_id_only_or_cross_batch_join(self):
        req = request("batch-synthetic-csv-2")
        other = request("batch-synthetic-json-1")["commands"][0]["source_identity"]
        self.assertEqual(other["external_id"], req["commands"][0]["source_identity"]["external_id"])
        req["commands"][0]["source_identity"] = other
        self.assertEqual(
            bridge.project(req)["steps"][0]["reason"], "bridge: source_identity_mismatch"
        )
        req = request()
        req["commands"][0]["source_identity"]["row_ordinal"] = True
        self.assertFalse(bridge.project(req)["steps"][0]["accepted"])

    def test_eligibility_uses_contracts_without_invented_readiness(self):
        view = bridge.inspect_case(KEY, synthetic_fixtures_only=True)
        self.assertEqual(view["eligibility"]["preparation"], ["draft_preparation"])
        self.assertEqual(view["eligibility"]["internal_review"], ["start_review"])
        self.assertEqual(view["eligibility"]["meaning"], "PURE_CONTRACT_ONLY")
        result = bridge.project(request(dimension="review", action="start_review"))
        self.assertTrue(result["steps"][0]["accepted"])
        self.assertEqual(result["initial"]["record"], result["final"]["record"])
        self.assertEqual(result["final"]["review"], "IN_REVIEW")

    def test_unsupported_moves_and_joins_never_activate(self):
        for dimension, action in (
            ("review", "complete_review"),
            ("preparation", "published"),
            ("preparation", "ready_for_future_review"),
            ("preparation_to_review", "start_review"),
            ("approval", "approve"),
        ):
            with self.subTest(dimension=dimension, action=action):
                step = bridge.project(request(dimension=dimension, action=action))["steps"][0]
                self.assertFalse(step["accepted"])
                self.assertEqual(step["before"], step["after"])
                if dimension not in ("preparation", "review"):
                    self.assertEqual(step["disposition"], "NOT_CONNECTED")

    def test_complete_snapshot_hash_catches_edited_history_with_same_revision(self):
        req = request()
        state = bridge.inspect_case(KEY, synthetic_fixtures_only=True)["initial"]
        state["record"]["history"][0]["editorial_note"] = "synthetic tamper"
        req["commands"][0]["expected_state"] = state_token(state)
        self.assertFalse(bridge.project(req)["steps"][0]["accepted"])

    def test_deterministic_detached_results_without_mutation(self):
        req = bridge.scenario(KEY, synthetic_fixtures_only=True)
        before = copy.deepcopy(req)
        first = bridge.project(req)
        second = bridge.project(req)
        self.assertEqual(req, before)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        first["initial"]["record"]["intake"]["question"] = "tamper"
        self.assertEqual(canonical_bytes(second), canonical_bytes(bridge.project(req)))

    def test_invalid_envelopes_and_unknown_cases_fail_closed(self):
        for key in ("history", "intake-7", "synthetic-malformed", "../source.zip", None, True):
            with self.subTest(key=key), self.assertRaises(bridge.BridgeError):
                bridge.inspect_case(key, synthetic_fixtures_only=True)
        for value in (False, 1, "true", None):
            with self.subTest(flag=value), self.assertRaises(bridge.BridgeError):
                bridge.inspect_case(KEY, synthetic_fixtures_only=value)
        req = request()
        for update in (
            {"synthetic_fixtures_only": False},
            {"schema": "wrong"},
            {"commands": [{}] * (bridge.MAX_COMMANDS + 1)},
            {"extra": True},
        ):
            with self.subTest(update=update), self.assertRaises(bridge.BridgeError):
                bridge.project(dict(req, **update))

    def test_malformed_command_rejects_without_hiding_later_valid_attempt(self):
        for invalid in (None, {}, {"action": "draft_preparation"}):
            req = request()
            req["commands"].insert(0, invalid)
            result = bridge.project(req)
            self.assertFalse(result["steps"][0]["accepted"])
            self.assertTrue(result["steps"][1]["accepted"])

    def test_bounded_json_types_and_bytes_reject_before_projection(self):
        for invalid in (
            float("nan"),
            1.0,
            ("tuple",),
            b"bytes",
            {1: "key"},
            "\ud800",
            2**60,
            "x" * (bridge.MAX_INPUT_BYTES + 1),
        ):
            req = request()
            req["commands"][0]["expected_state"] = invalid
            with self.subTest(kind=type(invalid)), self.assertRaises(bridge.BridgeError):
                bridge.project(req)
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(bridge.BridgeError):
            bridge.project(cycle)
        req = request()
        req["commands"] = []
        result = bridge.project(req)
        self.assertEqual(result["initial"], result["final"])

    def test_provider_fingerprint_corruption_is_rejected(self):
        workbench = build_prepared_workbench()
        bad_batch = replace(workbench.batches[0], raw_source="synthetic corrupt bytes")
        bad_workbench = replace(workbench, batches=(bad_batch, *workbench.batches[1:]))
        with patch.object(bridge, "build_prepared_workbench", return_value=bad_workbench):
            with self.assertRaisesRegex(bridge.BridgeError, "invalid_source_fingerprint"):
                bridge.inspect_case(KEY, synthetic_fixtures_only=True)

    def test_nested_reference_identity_changes_cannot_join(self):
        req = request()
        token = req["commands"][0]["source_identity"]
        token["reference_identities"][0]["verified"]["source_input_sha256"] = "0" * 64
        step = bridge.project(req)["steps"][0]
        self.assertEqual(step["reason"], "bridge: source_identity_mismatch")
        self.assertEqual(step["before"], step["after"])

    def test_repeated_large_strings_reject_before_full_serialization(self):
        # Aliased strings occupy little caller memory but expand in serialized JSON.
        repeated = ["x" * 600_000] * 3
        with patch.object(bridge, "canonical_bytes", side_effect=AssertionError("full allocation")):
            with self.assertRaisesRegex(bridge.BridgeError, "input_byte_limit"):
                bridge.project(repeated)


if __name__ == "__main__":
    unittest.main()
