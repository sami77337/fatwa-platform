"""Evidence must remain bound to exact packets and replayed workflow snapshots."""

import copy
import csv
import io
import json
import os
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.services import ExportError, build_export, encode_json
from apps.fast8_review_export.services import _project_case, build_preview, verify_preview
from apps.workflow_invariants.engine import canonical_bytes, replay, scenario


class PreviewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_files = dict(build_export(synthetic_fixtures_only=True).files)
        cls.source_report = json.loads(cls.source_files["report.json"])

    def build(self, scenario_name="rehearsal"):
        return build_preview(
            self.source_files,
            scenario_name=scenario_name,
            synthetic_fixtures_only=True,
        )

    def entry(self, key):
        return copy.deepcopy(
            next(
                item
                for item in self.source_report["cases"]
                if item["packet"]["identity"]["case_key"] == key
            )
        )

    def test_deterministic_preview_preserves_all_case_keys_and_original_bundle(self):
        before = self.source_files.copy()
        first = self.build()
        self.assertEqual(first.files, self.build().files)
        self.assertEqual(self.source_files, before)
        self.assertEqual(
            set(dict(first.files)), {"preview.json", "review-events.csv", "manifest.json"}
        )
        report = json.loads(first.file("preview.json"))
        self.assertEqual(report["schema"], "synthetic-review-export-preview.v1")
        expected_keys = [
            entry["packet"]["identity"]["case_key"] for entry in self.source_report["cases"]
        ]
        self.assertEqual([case["case_key"] for case in report["cases"]], expected_keys)
        self.assertEqual(len(report["cases"]), 20)
        self.assertIsNone(report["scholarly_decision"])
        self.assertEqual(report["persisted_review"], "NOT_CONNECTED")
        self.assertIn("Gate B NOT_PASSED", report["holds"])
        self.assertIn("NOT_DEPLOYED", report["holds"])
        verify_preview(dict(first.files), self.source_files, synthetic_fixtures_only=True)

    def test_only_exact_associated_case_contains_review_events_and_original_hashes(self):
        report = json.loads(self.build().file("preview.json"))
        connected = [case for case in report["cases"] if case["association"] == "CONNECTED"]
        self.assertEqual([case["case_key"] for case in connected], ["intake-7"])
        case = connected[0]
        self.assertEqual(case["snapshot"], "AVAILABLE")
        expected = replay(scenario("rehearsal"))
        steps = [step for step in expected["steps"] if step["event"]["dimension"] == "review"]
        self.assertEqual(len(case["events"]), 6)
        self.assertEqual([event["ordinal"] for event in case["events"]], [1, 4, 5, 6, 7, 8])
        self.assertEqual(
            [event["disposition"] for event in case["events"]],
            ["REJECTED", "APPLIED", "APPLIED", "APPLIED", "APPLIED", "REJECTED"],
        )
        for actual, step in zip(case["events"], steps, strict=True):
            self.assertEqual(actual, {"case_key": "intake-7", **step})
            for side in ("before", "after"):
                self.assertEqual(
                    actual[f"{side}_sha256"], sha256(canonical_bytes(actual[side])).hexdigest()
                )
            if not actual["accepted"]:
                self.assertEqual(actual["before_sha256"], actual["after_sha256"])
        entry = self.entry("intake-7")
        self.assertEqual(case["packet_sha256"], entry["packet_sha256"])
        self.assertEqual(case["source"], entry["packet"]["source"])
        for other in report["cases"]:
            if other["case_key"] != "intake-7":
                self.assertEqual(other["events"], [])
                self.assertIsNone(other["source"])

    def test_preparation_only_scenario_does_not_invent_review_events(self):
        report = json.loads(self.build("preparation").file("preview.json"))
        self.assertTrue(all(case["events"] == [] for case in report["cases"]))
        rows = list(
            csv.DictReader(
                io.StringIO(
                    self.build("preparation").file("review-events.csv").decode(), newline=""
                )
            )
        )
        self.assertEqual(rows, [])

    def test_missing_draft_is_unavailable_and_has_no_fabricated_event_snapshots(self):
        report = json.loads(self.build("blocked").file("preview.json"))
        unavailable = next(case for case in report["cases"] if case["case_key"] == "intake-1")
        self.assertEqual(unavailable["snapshot"], "UNAVAILABLE")
        self.assertEqual(unavailable["events"], [])
        self.assertIsNone(unavailable["source"])

    def test_manifest_pins_preview_and_every_original_source_file(self):
        files = dict(self.build().files)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(set(manifest["files"]), {"preview.json", "review-events.csv"})
        for name, metadata in manifest["files"].items():
            self.assertEqual(
                metadata, {"bytes": len(files[name]), "sha256": sha256(files[name]).hexdigest()}
            )
        self.assertEqual(set(manifest["source_files"]), set(self.source_files))
        for name, metadata in manifest["source_files"].items():
            raw = self.source_files[name]
            self.assertEqual(metadata, {"bytes": len(raw), "sha256": sha256(raw).hexdigest()})

    def test_csv_json_cells_roundtrip_snapshots_without_formula_prefixes(self):
        bundle = self.build()
        report = json.loads(bundle.file("preview.json"))
        raw = bundle.file("review-events.csv")
        self.assertIn(b"\r\n", raw)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
        expected = [event for case in report["cases"] for event in case["events"]]
        self.assertEqual(
            [{key: json.loads(value) for key, value in row.items()} for row in rows], expected
        )
        for row in rows:
            for cell in row.values():
                self.assertFalse(cell.startswith(("=", "+", "-", "@", "\t", "\r")))
        source = next(case["source"] for case in report["cases"] if case["source"] is not None)
        self.assertEqual(sha256(source["text"].encode("utf-8")).hexdigest(), source["text_sha256"])
        self.assertEqual(
            source["text"].encode("utf-8"),
            self.entry("intake-7")["packet"]["source"]["text"].encode("utf-8"),
        )

    def test_tampered_preview_and_rehashed_manifest_are_rejected(self):
        original = dict(self.build().files)
        for name in original:
            with self.subTest(name=name):
                changed = original.copy()
                changed[name] += b"\n"
                if name != "manifest.json":
                    manifest = json.loads(changed["manifest.json"])
                    manifest["files"][name] = {
                        "bytes": len(changed[name]),
                        "sha256": sha256(changed[name]).hexdigest(),
                    }
                    changed["manifest.json"] = encode_json(manifest)
                with self.assertRaises(ExportError):
                    verify_preview(changed, self.source_files, synthetic_fixtures_only=True)

    def test_changed_before_hash_cannot_be_laundered_by_rehashing_manifest(self):
        changed = dict(self.build().files)
        report = json.loads(changed["preview.json"])
        case = next(case for case in report["cases"] if case["events"])
        case["events"][0]["before_sha256"] = "0" * 64
        changed["preview.json"] = encode_json(report)
        manifest = json.loads(changed["manifest.json"])
        manifest["files"]["preview.json"] = {
            "bytes": len(changed["preview.json"]),
            "sha256": sha256(changed["preview.json"]).hexdigest(),
        }
        changed["manifest.json"] = encode_json(manifest)
        with self.assertRaises(ExportError):
            verify_preview(changed, self.source_files, synthetic_fixtures_only=True)

    def test_modified_source_and_rehashed_original_manifest_fail_before_projection(self):
        changed = self.source_files.copy()
        changed["cases.csv"] += b"\r\n"
        manifest = json.loads(changed["manifest.json"])
        manifest["files"]["cases.csv"] = {
            "bytes": len(changed["cases.csv"]),
            "sha256": sha256(changed["cases.csv"]).hexdigest(),
        }
        changed["manifest.json"] = encode_json(manifest)
        with self.assertRaises(ExportError):
            build_preview(changed, synthetic_fixtures_only=True)

    def test_unknown_scenario_and_mismatched_verification_scenario_reject(self):
        for name in ("unknown", "", None, True, ["rehearsal"]):
            with self.subTest(name=name), self.assertRaises(ExportError):
                self.build(name)
        files = dict(self.build().files)
        with self.assertRaises(ExportError):
            verify_preview(
                files, self.source_files, scenario_name="blocked", synthetic_fixtures_only=True
            )

    def test_default_off_and_production_guards(self):
        for flag in (False, None, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(ExportError):
                build_preview(self.source_files, synthetic_fixtures_only=flag)
        for environment in (
            {"FATWA_PRODUCTION": "1"},
            {"DJANGO_SETTINGS_MODULE": "config.settings.production"},
        ):
            with patch.dict(os.environ, environment), self.assertRaises(ExportError):
                self.build()
        with self.assertRaises(ExportError):
            verify_preview(dict(self.build().files), self.source_files)

    def test_preview_file_set_and_byte_types_are_strict(self):
        files = dict(self.build().files)
        invalid = (
            {},
            {**files, "extra.json": b"{}"},
            {**files, "preview.json": bytearray(files["preview.json"])},
            {**files, "preview.json": b"\xff"},
        )
        for supplied in invalid:
            with self.subTest(names=list(supplied)), self.assertRaises(ExportError):
                verify_preview(supplied, self.source_files, synthetic_fixtures_only=True)

    def test_external_id_collision_does_not_connect_a_different_case(self):
        first = self.entry("intake-1")
        duplicate = self.entry("intake-4")
        self.assertEqual(
            first["packet"]["identity"]["external_id"],
            duplicate["packet"]["identity"]["external_id"],
        )
        projected = _project_case(duplicate, replay(scenario("blocked")))
        self.assertEqual(projected["association"], "NOT_CONNECTED")
        self.assertEqual(projected["events"], [])
        self.assertIsNone(projected["source"])

    def test_source_identity_mismatch_omits_content_even_when_case_key_matches(self):
        original = replay(scenario("rehearsal"))
        for field, value in (
            ("source_sha256", "0" * 64),
            ("payload_sha256", "1" * 64),
            ("source_start", True),
            ("external_id", "synthetic-other"),
            ("reference_identities", []),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed["source_identity"][field] = value
                projected = _project_case(self.entry("intake-7"), changed)
                self.assertEqual(projected["association"], "NOT_CONNECTED")
                self.assertEqual(projected["events"], [])
                self.assertIsNone(projected["source"])

    def test_absent_or_different_initial_snapshot_cannot_supply_review_evidence(self):
        original = replay(scenario("rehearsal"))
        for replacement in (None, {**original["initial"]["record"], "history": []}):
            with self.subTest(record=replacement is None):
                changed = copy.deepcopy(original)
                changed["initial"]["record"] = replacement
                projected = _project_case(self.entry("intake-7"), changed)
                self.assertEqual(projected["snapshot"], "UNAVAILABLE")
                self.assertEqual(projected["events"], [])
                self.assertIsNone(projected["source"])

    def test_retry_evidence_remains_replay_and_is_not_reported_as_new_application(self):
        request = scenario("rehearsal")
        request["events"].append(copy.deepcopy(request["events"][3]))
        result = replay(request)
        projected = _project_case(self.entry("intake-7"), result)
        retry = projected["events"][-1]
        self.assertTrue(retry["accepted"])
        self.assertEqual(retry["disposition"], "REPLAY")
        self.assertEqual(retry["original_ordinal"], 4)
        self.assertEqual(retry["before_sha256"], retry["after_sha256"])
        self.assertEqual(retry["changed_paths"], [])

    def test_boolean_revision_number_cannot_alias_an_integer_snapshot(self):
        changed = replay(scenario("rehearsal"))
        self.assertEqual(changed["initial"]["record"]["history"][0]["number"], 1)
        changed["initial"]["record"]["history"][0]["number"] = True
        projected = _project_case(self.entry("intake-7"), changed)
        self.assertEqual(projected["association"], "NOT_CONNECTED")
        self.assertEqual(projected["snapshot"], "UNAVAILABLE")
        self.assertEqual(projected["events"], [])
        self.assertIsNone(projected["source"])

    def test_absent_case_association_cannot_fall_back_to_a_matching_snapshot(self):
        changed = replay(scenario("rehearsal"))
        changed["source_identity"].pop("case_key")
        projected = _project_case(self.entry("intake-7"), changed)
        self.assertEqual(projected["association"], "NOT_CONNECTED")
        self.assertEqual(projected["events"], [])
        self.assertIsNone(projected["source"])

    def test_different_intake_text_or_nonempty_history_omits_evidence(self):
        original = replay(scenario("rehearsal"))
        for field in ("intake", "history"):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                record = changed["initial"]["record"]
                if field == "intake":
                    record["intake"]["question"] += "\r\nسُؤَالٌ اصطناعي e\u0301"
                else:
                    record["history"][0]["state"] = "draft_preparation"
                projected = _project_case(self.entry("intake-7"), changed)
                self.assertEqual(projected["association"], "NOT_CONNECTED")
                self.assertEqual(projected["snapshot"], "UNAVAILABLE")
                self.assertEqual(projected["events"], [])
                self.assertIsNone(projected["source"])
