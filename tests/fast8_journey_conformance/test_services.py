import copy
import json
import os
import socket
from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.editorial_export.services import encode_json
from apps.fast8_journey_conformance import services as s


class ConformanceTests(TestCase):
    def contract(self, key="batch-synthetic-csv-1"):
        data = json.loads(s.default_contract())
        data["scenarios"] = [row for row in data["scenarios"] if row["id"] == key]
        return data

    def run_contract(self, data=None, **kwargs):
        return s.run_conformance(
            encode_json(data) if data is not None else None,
            synthetic_fixtures_only=True,
            **kwargs,
        ).payload()

    def test_all_pinned_scenarios_run_deterministically_without_network(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            first = s.run_conformance(synthetic_fixtures_only=True)
            second = s.run_conformance(synthetic_fixtures_only=True)
        self.assertEqual(first.json_bytes, second.json_bytes)
        report = first.payload()
        self.assertEqual(len(report["scenarios"]), 21)
        self.assertEqual(report["result"], "PASS_WITH_GAPS")
        self.assertEqual(
            report["permission"],
            {"effect": "DENY", "allowed": False, "case_binding": "NOT_CONNECTED"},
        )
        self.assertEqual(report["execution"]["http"], "NOT_RUN")
        self.assertEqual(report["execution"]["owner_archives"], "NOT_SUPPLIED")
        for scenario in report["scenarios"]:
            self.assertEqual(scenario["stages"]["persisted_review"]["status"], "NOT_CONNECTED")
            self.assertEqual(scenario["extensions"][0]["execution"], "NOT_RUN")

    def test_each_identity_field_and_packet_pin_reject_stale_or_missing(self):
        data = self.contract()
        for field, value in data["scenarios"][0]["anchor"]["identity"].items():
            for mode in ("missing", "changed"):
                changed = copy.deepcopy(data)
                identity = changed["scenarios"][0]["anchor"]["identity"]
                if mode == "missing":
                    del identity[field]
                else:
                    identity[field] = value + "x" if type(value) is str else 99
                with self.subTest(field=field, mode=mode), self.assertRaises(s.ConformanceError):
                    self.run_contract(changed)
        data["scenarios"][0]["anchor"]["packet_sha256"] = "0" * 64
        with self.assertRaises(s.ConformanceError):
            self.run_contract(data)

    def test_bool_float_and_extra_fields_cannot_alias_complete_identity(self):
        for value in (True, 1.0, "1"):
            data = self.contract()
            data["scenarios"][0]["anchor"]["identity"]["row_ordinal"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                s.run_conformance(json.dumps(data).encode(), synthetic_fixtures_only=True)
        data = self.contract()
        data["scenarios"][0]["anchor"]["identity"]["alias"] = "synthetic-csv"
        with self.assertRaises(s.ConformanceError):
            self.run_contract(data)

    def test_duplicate_external_id_does_not_join_two_source_rows(self):
        first = self.contract("intake-1")
        fourth = self.contract("intake-4")
        one = first["scenarios"][0]["anchor"]
        four = fourth["scenarios"][0]["anchor"]
        self.assertEqual(one["identity"]["external_id"], four["identity"]["external_id"])
        self.assertNotEqual(one["identity"], four["identity"])
        one["identity"]["case_key"] = "intake-4"
        with self.assertRaises(s.ConformanceError):
            self.run_contract(first)

    def test_transcript_stays_separate_and_required_missing_chain_fails_closed(self):
        data = self.contract("transcript-receipt")
        scenario = self.run_contract(data)["scenarios"][0]
        self.assertEqual(scenario["stages"]["prepared_receipt"]["draft_count"], 0)
        self.assertEqual(scenario["stages"]["queue_triage_packet"]["status"], "NOT_CONNECTED")
        self.assertEqual(
            scenario["stages"]["transcript"]["evidence"]["invalid_timestamp"], "REJECTED"
        )
        data["scenarios"][0]["required"].append("queue_triage_packet")
        result = self.run_contract(data)
        self.assertEqual(result["result"], "NOT_CONNECTED")
        self.assertEqual(result["scenarios"][0]["required_unavailable"], ["queue_triage_packet"])
        data["scenarios"][0]["anchor"]["input_sha256"] = "0" * 64
        with self.assertRaises(s.ConformanceError):
            self.run_contract(data)

    def test_projection_is_not_persisted_review_and_rejected_draft_stays_missing(self):
        ready = self.run_contract(self.contract("intake-7"))["scenarios"][0]
        projection = ready["stages"]["review_projection"]
        self.assertEqual(projection["projection"]["review"], "REVIEWED_INTERNAL")
        self.assertIs(projection["persisted"], False)
        self.assertIs(projection["scholarly_approval"], False)
        blocked = self.run_contract(self.contract("intake-1"))["scenarios"][0]
        self.assertIsNone(blocked["stages"]["review_projection"]["projection"]["record"])
        self.assertTrue(
            all(not step["accepted"] for step in blocked["stages"]["review_projection"]["steps"])
        )
        data = self.contract("intake-7")
        data["scenarios"][0]["required"].append("persisted_review")
        self.assertEqual(self.run_contract(data)["result"], "NOT_CONNECTED")

    def test_research_missing_catalog_closes_links_and_does_not_imply_approval(self):
        ready = self.run_contract(self.contract("intake-7"))["scenarios"][0]
        refs = ready["stages"]["research"]["references"]
        self.assertTrue(any(ref["status"] == "verified" for ref in refs))
        self.assertTrue(all(ref["empty_catalog_url"] is None for ref in refs))
        with patch.object(s, "_asserted_catalog", return_value=()):
            missing = self.run_contract(self.contract("intake-7"))["scenarios"][0]
        self.assertTrue(
            all(ref["catalog_url"] is None for ref in missing["stages"]["research"]["references"])
        )

    def test_extension_cannot_replace_core_gaps_and_is_identity_bound(self):
        probe = Mock(side_effect=lambda anchor: s.AdapterEvidence(anchor, "PASS"))
        data = self.contract()
        result = self.run_contract(data, probes={"fast8_adapter": probe})["scenarios"][0]
        self.assertEqual(result["extensions"][0]["status"], "PASS")
        self.assertEqual(result["stages"]["persisted_review"]["status"], "NOT_CONNECTED")
        self.assertEqual(probe.call_count, 1)
        for status in ("APPROVED", "CONNECTED"):
            with self.subTest(status=status), self.assertRaises(s.ConformanceError):
                self.run_contract(
                    data, probes={"fast8_adapter": lambda a: s.AdapterEvidence(a, status)}
                )
        with self.assertRaises(s.ConformanceError):
            self.run_contract(
                data,
                probes={
                    "fast8_adapter": lambda a: s.AdapterEvidence(s.ScenarioAnchor(b"{}"), "PASS")
                },
            )

    def test_all_pins_checked_before_any_extension_runs(self):
        data = self.contract()
        second = self.contract("intake-7")["scenarios"][0]
        second["anchor"]["packet_sha256"] = "0" * 64
        data["scenarios"].append(second)
        probe = Mock()
        with self.assertRaises(s.ConformanceError):
            self.run_contract(data, probes={"fast8_adapter": probe})
        probe.assert_not_called()

    def test_extension_mutable_or_view_receipts_cannot_claim_pass(self):
        for wrapper in (bytearray, memoryview):
            with self.subTest(wrapper=wrapper), self.assertRaises(s.ConformanceError):
                self.run_contract(
                    self.contract(),
                    probes={
                        "fast8_adapter": lambda anchor: s.AdapterEvidence(
                            s.ScenarioAnchor(wrapper(anchor.json_bytes)), "PASS"
                        )
                    },
                )

    def test_stale_research_catalog_pins_close_link_even_when_numeric_ids_match(self):
        catalog = s._asserted_catalog()
        for field, value in (
            ("heading_title", "SYNTHETIC-STALE-TITLE"),
            ("path", ("SYNTHETIC-STALE-PATH",)),
            ("source_input_sha256", "0" * 64),
            ("source_archive_sha256", "0" * 64),
        ):
            stale = tuple(replace(row, **{field: value}) for row in catalog)
            with (
                self.subTest(field=field),
                patch.object(s, "_asserted_catalog", return_value=stale),
            ):
                result = self.run_contract(self.contract("intake-7"))["scenarios"][0]
                refs = result["stages"]["research"]["references"]
                self.assertTrue(refs)
                self.assertTrue(all(ref["status"] == "unverified" for ref in refs))
                self.assertTrue(all(ref["catalog_url"] is None for ref in refs))

    def test_invalid_contracts_and_unknown_selector_reject_before_service_run(self):
        data = self.contract()
        repeated = copy.deepcopy(data)
        repeated["scenarios"].append(repeated["scenarios"][0])
        unknown = copy.deepcopy(data)
        unknown["scenarios"][0]["unexpected"] = True
        no_required = copy.deepcopy(data)
        no_required["scenarios"][0]["required"] = []
        payloads = [
            b"{}",
            b'{"schema":1,"schema":2}',
            b"[",
            b"\xff",
            b" " * (s.MAX_CONTRACT_BYTES + 1),
            encode_json(repeated),
            encode_json(unknown),
            encode_json(no_required),
        ]
        with patch.object(s, "run_integration") as run:
            for raw in payloads:
                with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                    s.run_conformance(raw, synthetic_fixtures_only=True)
            with self.assertRaises(s.ConformanceError):
                self.run_contract(data, scenario="nonexistent")
            run.assert_not_called()

    def test_development_guard_precedes_fixture_reads(self):
        with patch.object(s, "default_contract") as read:
            for flag in (False, None, 1, "true"):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    s.run_conformance(synthetic_fixtures_only=flag)
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}), self.assertRaises(ValueError):
                self.run_contract()
            read.assert_not_called()
