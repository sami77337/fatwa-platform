"""Real replay integration plus isolated synthetic differ tests.

Different snapshots cannot both pass the current fixed-fixture contract. Tests
of changed values call only the private differ; they do not claim those altered
reports are accepted bundles or replace the public verifier with a permissive one.
"""

import copy
import json
import os
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export import comparison, services


class ComparisonTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.files = dict(services.build_export(synthetic_fixtures_only=True).files)

    def compare(self, before=None, after=None):
        return comparison.compare_exports(
            self.files if before is None else before,
            self.files if after is None else after,
            synthetic_fixtures_only=True,
        )

    def reports(self):
        before = json.loads(self.files["report.json"])
        return before, copy.deepcopy(before)

    def test_real_replay_is_deterministic_and_binds_both_complete_inputs(self):
        original = self.files.copy()
        with patch.object(services, "verify_export", wraps=services.verify_export) as verifier:
            raw = self.compare()
        self.assertEqual(verifier.call_count, 2)
        self.assertEqual(raw, self.compare(after=dict(reversed(list(self.files.items())))))
        self.assertEqual(self.files, original)
        result = json.loads(raw)
        self.assertTrue(result["identical"])
        self.assertEqual(result["holds"], list(services.HOLDS))
        self.assertEqual(result["cases"], {"added": [], "removed": [], "changed": []})
        self.assertEqual(result["batches"], {"added": [], "removed": [], "changed": []})
        self.assertEqual(result["manifest"], [])
        self.assertEqual(result["report_metadata"], [])
        for side in ("before", "after"):
            for name, contents in self.files.items():
                self.assertEqual(
                    result["inputs"][side][name],
                    {"bytes": len(contents), "sha256": sha256(contents).hexdigest()},
                )

    def test_both_inputs_must_pass_before_any_json_is_parsed(self):
        invalid = {**self.files, "report.json": b"not JSON"}
        for before, after in ((invalid, self.files), (self.files, invalid)):
            with (
                self.subTest(side="before" if before is invalid else "after"),
                patch.object(comparison, "_compare_reports") as differ,
                patch.object(comparison.json, "loads", side_effect=AssertionError("parsed")),
                patch.object(
                    services,
                    "build_export",
                    return_value=services.ExportBundle(tuple(self.files.items())),
                ),
                self.assertRaisesRegex(services.ExportError, "replay_mismatch"),
            ):
                self.compare(before, after)
            differ.assert_not_called()

    def test_rehashed_tampering_incompatible_and_ambiguous_reports_are_rejected(self):
        for mutation in ("text", "schema", "duplicate_case", "duplicate_batch"):
            before, altered = self.reports()
            if mutation == "text":
                altered["cases"][0]["packet"]["source"]["text"] += " synthetic tamper"
            elif mutation == "schema":
                altered["schema"] = "synthetic-editorial-export.v999"
            elif mutation == "duplicate_case":
                altered["cases"].append(copy.deepcopy(altered["cases"][0]))
            else:
                altered["batches"].append(copy.deepcopy(altered["batches"][0]))
            files = self.files.copy()
            files["report.json"] = services.encode_json(altered)
            manifest = json.loads(files["manifest.json"])
            manifest["files"]["report.json"] = {
                "bytes": len(files["report.json"]),
                "sha256": sha256(files["report.json"]).hexdigest(),
            }
            files["manifest.json"] = services.encode_json(manifest)
            for left, right in ((files, self.files), (self.files, files)):
                with self.subTest(mutation=mutation), self.assertRaises(services.ExportError):
                    self.compare(left, right)

    def test_guards_file_types_and_fixed_input_bounds(self):
        with patch.object(services, "verify_export") as verifier:
            for flag in (False, None, 1, "true"):
                with self.assertRaises(services.ExportError):
                    comparison.compare_exports(self.files, self.files, synthetic_fixtures_only=flag)
            with (
                patch.dict(os.environ, FATWA_PRODUCTION="1"),
                self.assertRaises(services.ExportError),
            ):
                self.compare()
            verifier.assert_not_called()
        for invalid in (
            [],
            {},
            {**self.files, "extra": b""},
            {**self.files, "report.json": bytearray(self.files["report.json"])},
            {**self.files, "report.json": b"x" * (services.MAX_FILE_BYTES + 1)},
        ):
            for before, after in ((invalid, self.files), (self.files, invalid)):
                with self.subTest(type=type(invalid)), self.assertRaises(services.ExportError):
                    self.compare(before, after)
        with patch.object(services, "MAX_BUNDLE_BYTES", 1), self.assertRaises(services.ExportError):
            self.compare()

    def test_complete_report_must_fit_existing_output_bounds(self):
        # Verification remains real. Lower only the final comparison output cap.
        encode = services.encode_json

        def bounded_result(value):
            if (
                isinstance(value, dict)
                and value.get("schema") == "synthetic-editorial-export-comparison.v1"
            ):
                with patch.object(services, "MAX_FILE_BYTES", 1):
                    return encode(value)
            return encode(value)

        with patch.object(services, "encode_json", side_effect=bounded_result):
            with self.assertRaisesRegex(services.ExportError, "byte_limit"):
                self.compare()

    def test_added_removed_exact_identities_never_join_external_ids(self):
        before, after = self.reports()
        removed = after["cases"].pop(0)
        added = copy.deepcopy(removed)
        # Same external ID, different exact key; composed/decomposed keys differ.
        added["packet"]["identity"]["case_key"] = "synthetic-é"
        added["navigation"]["case_key"] = "synthetic-é"
        after["cases"].append(added)
        second = copy.deepcopy(added)
        second["packet"]["identity"]["case_key"] = "synthetic-e\u0301"
        second["navigation"]["case_key"] = "synthetic-e\u0301"
        after["cases"].insert(0, second)
        result = comparison._compare_reports(before, after)
        self.assertEqual(
            [e["identity"]["case_key"] for e in result["cases"]["added"]],
            ["synthetic-e\u0301", "synthetic-é"],
        )
        self.assertEqual(result["cases"]["removed"][0]["identity"], removed["packet"]["identity"])
        self.assertEqual(result["cases"]["changed"], [])
        self.assertEqual(result["batches"]["changed"][0]["changes"], [])
        after["cases"].reverse()
        self.assertEqual(result, comparison._compare_reports(before, after))

    def test_packet_status_source_and_provenance_changes_are_lossless(self):
        before, after = self.reports()
        entry = after["cases"][0]
        packet = entry["packet"]
        packet["source"]["text"] = "  سُؤَالٌ\r\n e\u0301 =1+1  "
        packet["identity"]["external_id"] = None
        packet["identity"]["input_sha256"] = "c" * 64
        packet["intake"]["original_fields"]["synthetic/key~"] = " exact\r\n"
        packet["receipt"]["intake_state"] = "pending"
        packet["receipt"]["status"] = "pending"
        packet["preparation_errors"] = [{"code": "SYNTHETIC_TEST"}]
        packet["reference_verification"]["results"][0]["status"] = "unresolved"
        packet["reference_verification"]["results"][0]["verified_identity"]["source_id"] = (
            "synthetic-other"
        )
        packet["snapshots"][0]["editorial_note"] = "synthetic comparison test"
        entry["packet_sha256"] = sha256(services.encode_json(packet)).hexdigest()
        result = comparison._compare_reports(before, after)
        changed = result["cases"]["changed"][0]
        self.assertTrue(changed["packet_digest_changed"])
        self.assertEqual(changed["packet_sha256"]["after"], entry["packet_sha256"])
        groups = changed["changes"]
        self.assertEqual(set(groups), {"preparation", "reference", "source_provenance", "packet"})
        self.assertTrue(all(groups.values()))
        source = next(
            c for c in groups["source_provenance"] if c["path"] == ["packet", "source", "text"]
        )
        self.assertEqual(source["after"]["value"], packet["source"]["text"])
        added_field = next(
            c for c in groups["source_provenance"] if c["path"][-1] == "synthetic/key~"
        )
        self.assertEqual(added_field["before"], {"present": False, "value": None})
        reference = groups["reference"][0]
        self.assertEqual(reference["after"]["value"], packet["reference_verification"]["results"])
        self.assertEqual(json.loads(services.encode_json(result)), result)
        # Diffing does not mutate either input and reversing preserves direction.
        self.assertEqual(before, json.loads(self.files["report.json"]))
        reverse = comparison._compare_reports(after, before)
        reverse_source = next(
            c
            for c in reverse["cases"]["changed"][0]["changes"]["source_provenance"]
            if c["path"] == source["path"]
        )
        self.assertEqual(reverse_source["before"], source["after"])

    def test_batch_add_remove_zero_row_failure_and_exact_raw_changes(self):
        before, after = self.reports()
        removed = after["batches"].pop(0)
        failed = next(b for b in after["batches"] if b["record_count"] == 0)
        failed["raw_source"] += "\r\n e\u0301 "
        failed["error_code"] = "SYNTHETIC_CHANGED"
        added = copy.deepcopy(removed)
        added["batch_id"] = "synthetic-added"
        after["batches"].append(added)
        result = comparison._compare_reports(before, after)
        self.assertEqual(result["batches"]["added"], [{"batch": added, "members": []}])
        self.assertEqual(result["batches"]["removed"][0]["batch"], removed)
        changed = result["batches"]["changed"][0]
        self.assertEqual(changed["batch_id"], failed["batch_id"])
        self.assertEqual(changed["before_members"], [])
        self.assertEqual(changed["after_members"], [])
        self.assertEqual(changed["changes"][-1]["after"]["value"], failed["raw_source"])

    def test_defensive_contract_and_identity_checks(self):
        for mutation in ("schema", "packet_schema", "case", "batch", "navigation"):
            before, after = self.reports()
            if mutation == "schema":
                after["schema"] = "unknown"
            elif mutation == "packet_schema":
                after["cases"][0]["packet"]["schema"] = "unknown"
            elif mutation == "case":
                after["cases"].append(copy.deepcopy(after["cases"][0]))
            elif mutation == "batch":
                after["batches"].append(copy.deepcopy(after["batches"][0]))
            else:
                after["cases"][0]["navigation"]["case_key"] = "different"
            with self.subTest(mutation=mutation), self.assertRaises(services.ExportError):
                comparison._compare_reports(before, after)

    def test_diff_distinguishes_missing_null_types_and_array_order(self):
        before = {"null": None, "typed": [True], "ordered": [1, 2]}
        after = {"new_null": None, "typed": [1], "ordered": [2, 1]}
        diff = comparison._differences(before, after)
        self.assertEqual(
            [c["path"] for c in diff], [["new_null"], ["null"], ["ordered"], ["typed"]]
        )
        self.assertFalse(diff[0]["before"]["present"])
        self.assertTrue(diff[0]["after"]["present"])
