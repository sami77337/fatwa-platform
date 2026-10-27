import copy
import json
import unittest
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_export import services as exports
from apps.editorial_workbench import packets
from apps.editorial_workbench.services import build_prepared_workbench
from apps.fast8_prepared_review import services as prepared
from apps.fast8_review_export import services as review
from apps.fast9_prepared_review_lineage import services as lineage
from apps.workflow_invariants import engine

KEY = "batch-synthetic-csv-1"


class LineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = dict(exports.build_export(synthetic_fixtures_only=True).files)
        cls.preview = dict(review.build_preview(cls.source, synthetic_fixtures_only=True).files)

    def build(self, key=KEY, **kwargs):
        return lineage.build_evidence(
            prepared.scenario(key, synthetic_fixtures_only=True),
            source_files=self.source,
            review_files=self.preview,
            synthetic_fixtures_only=True,
            **kwargs,
        )

    def test_real_composition_preserves_packet_snapshot_and_member_hashes(self):
        result = self.build()
        expected = prepared.project(prepared.scenario(KEY, synthetic_fixtures_only=True))
        self.assertEqual(result["status"], "SUPPORTED")
        self.assertEqual(result["prepared"], expected)
        self.assertEqual(result["joins"]["prepared_to_packet"]["status"], "SUPPORTED")
        self.assertEqual(result["joins"]["initial_snapshot_to_export"]["status"], "SUPPORTED")
        packet = result["packet"]
        self.assertEqual(packet["snapshots"], expected["initial"]["record"]["history"])
        self.assertEqual(
            result["packet_verification"]["packet_sha256"],
            sha256(packets.serialize_packet(packet)).hexdigest(),
        )
        for group, files in (("source_members", self.source), ("review_members", self.preview)):
            self.assertEqual(
                result[group],
                {
                    name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
                    for name, raw in files.items()
                },
            )

    def test_no_bridge_to_stock_workflow_or_persisted_review(self):
        result = self.build()
        for name in (
            "prepared_to_workflow_replay",
            "projected_review_to_export",
            "persisted_review",
        ):
            self.assertEqual(result["joins"][name]["status"], "NOT_CONNECTED")
        self.assertEqual(result["review_export_case"]["events"], [])
        self.assertEqual(result["review_export_case"]["association"], "NOT_CONNECTED")
        replay = engine.replay(engine.scenario("rehearsal"))
        self.assertEqual(result["workflow_replay"]["source_identity"], replay["source_identity"])
        self.assertEqual(
            result["workflow_replay"]["result_sha256"],
            sha256(engine.canonical_bytes(replay)).hexdigest(),
        )
        self.assertEqual(result["execution"]["postgresql"]["status"], "NOT_RUN")

    def test_unicode_crlf_parent_row_and_timestamps_are_exact(self):
        result = self.build()
        case = next(c for c in build_prepared_workbench().cases if c.key == KEY)
        identity = result["prepared"]["source_identity"]
        self.assertEqual(
            result["lineage_identity"],
            {
                "case_key": KEY,
                "parent_batch_id": case.batch_id,
                "parent_payload_sha256": case.payload_sha256,
                "row_ordinal": case.row_ordinal,
                "external_id": case.external_id,
                "parsed_row_sha256": sha256(case.raw_source.encode("utf-8")).hexdigest(),
                "prepared_case_sha256": identity["prepared_case_sha256"],
            },
        )
        question = result["packet"]["intake"]["question"]
        self.assertEqual(question, case.question)
        self.assertIn("\r\n", question)
        self.assertIn("e\u0301", question)
        self.assertIn("سُؤَالٌ", question)
        self.assertEqual(result["packet"]["source"]["text"], case.raw_source)
        self.assertIsNone(result["packet"]["identity"]["source_start"])

    def test_stale_and_altered_source_attempts_remain_rejected_without_state_change(self):
        result = self.build()
        steps = result["prepared"]["steps"]
        reasons = {step["reason"] for step in steps}
        self.assertIn("bridge: state_snapshot_mismatch", reasons)
        self.assertIn("bridge: source_identity_mismatch", reasons)
        for step, attempt in zip(steps, result["attempts"], strict=True):
            self.assertEqual(attempt["ordinal"], step["ordinal"])
            self.assertEqual(
                attempt["status"], "SUPPORTED" if step["accepted"] else step["disposition"]
            )
            if not step["accepted"]:
                self.assertEqual(step["before"], step["after"])
        self.assertEqual(result["prepared"]["final"]["record"]["history"][-1]["answer"], "")

    def test_every_prepared_row_including_absent_drafts(self):
        for case in build_prepared_workbench().cases:
            with self.subTest(case=case.key):
                result = self.build(case.key)
                self.assertEqual(result["packet"]["identity"]["row_ordinal"], case.row_ordinal)
                if case.record is None:
                    self.assertIsNone(result["prepared"]["final"]["record"])
                    self.assertEqual(result["packet"]["snapshots"], [])
                    self.assertEqual(
                        result["joins"]["initial_snapshot_to_export"]["status"], "NOT_CONNECTED"
                    )
                    self.assertFalse(any(s["accepted"] for s in result["prepared"]["steps"]))

    def test_shared_external_id_does_not_merge_distinct_rows(self):
        left, right = self.build("batch-synthetic-csv-2"), self.build("batch-synthetic-json-1")
        self.assertEqual(
            left["lineage_identity"]["external_id"], right["lineage_identity"]["external_id"]
        )
        self.assertNotEqual(left["lineage_identity"], right["lineage_identity"])
        self.assertNotEqual(
            left["packet_verification"]["packet_sha256"],
            right["packet_verification"]["packet_sha256"],
        )

    def test_altered_export_and_rehashed_manifest_reject(self):
        for name in self.source:
            changed = self.source.copy()
            changed[name] += b"\n"
            with self.subTest(member=name), self.assertRaises(lineage.LineageError):
                lineage.build_evidence(
                    prepared.scenario(KEY, synthetic_fixtures_only=True),
                    source_files=changed,
                    synthetic_fixtures_only=True,
                )
        changed = self.source.copy()
        changed["cases.csv"] += b"\r\n"
        manifest = json.loads(changed["manifest.json"])
        manifest["files"]["cases.csv"] = {
            "bytes": len(changed["cases.csv"]),
            "sha256": sha256(changed["cases.csv"]).hexdigest(),
        }
        changed["manifest.json"] = exports.encode_json(manifest)
        with self.assertRaises(lineage.LineageError):
            lineage.build_evidence(
                prepared.scenario(KEY, synthetic_fixtures_only=True),
                source_files=changed,
                synthetic_fixtures_only=True,
            )

    def test_altered_preview_or_wrong_scenario_reject(self):
        for name in self.preview:
            changed = self.preview.copy()
            changed[name] += b"\n"
            with self.subTest(member=name), self.assertRaises(lineage.LineageError):
                lineage.build_evidence(
                    prepared.scenario(KEY, synthetic_fixtures_only=True),
                    source_files=self.source,
                    review_files=changed,
                    synthetic_fixtures_only=True,
                )
        with self.assertRaises(lineage.LineageError):
            self.build(scenario_name="blocked")

    def test_deterministic_detached_record_and_no_input_mutation(self):
        req = prepared.scenario(KEY, synthetic_fixtures_only=True)
        before = copy.deepcopy(req)
        first = lineage.build_evidence(req, synthetic_fixtures_only=True)
        self.assertEqual(req, before)
        raw = lineage.encode_evidence(first)
        self.assertEqual(raw, lineage.encode_evidence(self.build()))
        first["prepared"]["final"]["review"] = "tampered"
        self.assertEqual(raw, lineage.encode_evidence(self.build()))

    def test_default_off_unknown_case_and_invalid_envelope(self):
        req = prepared.scenario(KEY, synthetic_fixtures_only=True)
        for flag in (False, None, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(lineage.LineageError):
                lineage.build_evidence(req, synthetic_fixtures_only=flag)
        for value in ({}, None, {**req, "case_key": "intake-7"}):
            with self.subTest(value=value), self.assertRaises(lineage.LineageError):
                lineage.build_evidence(value, synthetic_fixtures_only=True)

    def test_all_stock_scenarios_stay_unjoined_to_prepared_review(self):
        for name in review.SCENARIOS:
            with self.subTest(scenario=name):
                result = lineage.build_evidence(
                    prepared.scenario(KEY, synthetic_fixtures_only=True),
                    scenario_name=name,
                    synthetic_fixtures_only=True,
                )
                self.assertEqual(result["workflow_replay"]["scenario"], name)
                self.assertEqual(result["review_export_case"]["events"], [])
                self.assertEqual(
                    result["joins"]["prepared_to_workflow_replay"]["status"], "NOT_CONNECTED"
                )

    def test_provider_drift_cannot_claim_a_join_to_verified_export(self):
        # Fault injection at the prepared provider boundary: a valid export
        # must not mask mismatched parent, exact text, references or snapshots.
        req = prepared.scenario(KEY, synthetic_fixtures_only=True)
        original = prepared.project(req)
        mutations = (
            ("source_identity", "row_ordinal", True),
            ("source_identity", "batch_id", "another-synthetic-batch"),
            ("source_identity", "payload_sha256", "0" * 64),
            ("source_identity", "parsed_row_sha256", "0" * 64),
            ("source", "row_text", original["source"]["row_text"].replace("e\u0301", "é")),
            (
                "source",
                "batch_raw_text",
                original["source"]["batch_raw_text"].replace("\r\n", "\n"),
            ),
            ("source", "references", []),
            ("initial", "record", None),
        )
        for section, field, value in mutations:
            changed = copy.deepcopy(original)
            changed[section][field] = value
            with self.subTest(section=section, field=field):
                with patch.object(prepared, "project", return_value=changed):
                    with self.assertRaises(lineage.LineageError):
                        self.build()
        changed = copy.deepcopy(original)
        changed["initial"]["record"]["history"][0]["editorial_note"] = "synthetic drift"
        with patch.object(prepared, "project", return_value=changed):
            with self.assertRaisesRegex(lineage.LineageError, "initial_snapshot_mismatch"):
                self.build()
