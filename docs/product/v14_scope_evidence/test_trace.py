"""Negative attribution checks, not product or source-byte validation."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v14_trace_build", HERE / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class TraceTests(unittest.TestCase):
    def test_all_556_rows_preserve_every_historical_field(self):
        baseline = build.baseline()["matrix.json"]
        current = json.loads(build.outputs()["matrix.json"])
        self.assertEqual(len(current), 556)
        for old, new in zip(baseline, current, strict=True):
            new.pop("v14")
            self.assertEqual(old, new)

    def test_generated_outputs_are_reproducible(self):
        for name, text in build.outputs().items():
            self.assertEqual((HERE / name).read_bytes(), text.encode())

    def test_valid_attributed_source_receipt(self):
        build.validate_source(build.read("source_lineage.json"))

    def rejected_source(self, mutate):
        value = copy.deepcopy(build.read("source_lineage.json"))
        mutate(value)
        with self.assertRaises(AssertionError):
            build.validate_source(value)

    def test_reject_cloud_verification_claim(self):
        self.rejected_source(lambda v: v["boundaries"].update(cloud_source_bytes_verified=True))

    def test_reject_authorship_and_acceptance_inference(self):
        for field in ("authoring_provenance_established", "semantic_approval", "acceptance"):
            with self.subTest(field=field):
                self.rejected_source(lambda v: v["boundaries"].update({field: True}))

    def test_reject_docx_unverified_regression(self):
        self.rejected_source(lambda v: v["artifacts"]["docx"].update(status="UNVERIFIED"))

    def test_reject_workbook_conflation(self):
        self.rejected_source(lambda v: v["artifacts"]["reference_xlsx"].update(bytes=384127))
        self.rejected_source(
            lambda v: v["artifacts"]["historical_xlsx"].update(transformation_chain="MATCH")
        )

    def test_reject_lost_serialization_difference(self):
        self.rejected_source(lambda v: v["serialization_differences"].update(count=0))
        self.rejected_source(
            lambda v: v["serialization_differences"].update(whole_string_equality=True)
        )

    def test_reject_receipt_byte_inspection_inference(self):
        self.rejected_source(lambda v: v.update(receipt_bytes_inspected_here=True))

    def test_reject_runtime_credit_without_review(self):
        value = build.read("evidence.json")
        value["groups"] = [{"sha": build.BASE_SHA, "state": "PASS"}]
        with self.assertRaises(AssertionError):
            build.validate_evidence(value)

    def test_reject_new_percentage_or_status_upgrade(self):
        for key, change in (("status_upgrades", 1), ("new_percentage", 84), ("acceptance", "PASS")):
            value = build.read("evidence.json")
            value[key] = change
            with self.subTest(key=key), self.assertRaises(AssertionError):
                build.validate_evidence(value)


if __name__ == "__main__":
    unittest.main()
