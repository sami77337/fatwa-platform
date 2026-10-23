"""Serialization contracts over fabricated Wave7 data; no owner archive or DB."""

import hashlib
import json
import unittest
from dataclasses import replace

from apps.intake_workflow import contracts as c, fixtures
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading


ROOT = Heading(
    7001, 1, "مرجع اصطناعي لتجارب Wave7", "كِتَابٌ اصطناعي", "الأول", 7,
    ("كِتَابٌ اصطناعي",), c.SOURCE_IDENTITY["source_namespace"], "622",
    c.SOURCE_IDENTITY["source_input_sha256"], c.SOURCE_IDENTITY["edition_key"],
    c.SOURCE_IDENTITY["source_archive_sha256"],
)


class DiagnosticSerializationContractTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixtures.synthetic_payload()
        self.report = build_reference_diagnostics(
            self.raw, synthetic_fixtures_only=True, catalog_rows=(ROOT,),
        )
        self.item = self.report.items[0]
        self.reference = self.item.references[0]

    def assert_rejected(self, report):
        for boundary in (report.to_payload, report.json_bytes):
            with self.subTest(boundary=boundary.__name__), self.assertRaises(c.ContractError):
                boundary()

    def with_reference(self, reference):
        return replace(self.report, items=(replace(self.item, references=(reference,)),))

    def test_valid_export_retains_baseline_utf8_bytes_and_source_identity(self):
        report = build_reference_diagnostics(self.raw, synthetic_fixtures_only=True)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),
                         "cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb")
        self.assertEqual(hashlib.sha256(report.json_bytes()).hexdigest(),
                         "5f9fde267fdd6d0b4b31da89efa287b09eeeae78f6061ea845d7032a0a88710e")
        self.assertEqual(len(report.json_bytes()), 5190)
        self.assertEqual(json.loads(report.json_bytes()), report.to_payload())

    def test_mutable_nested_containers_cannot_be_exported(self):
        malformed = (
            replace(self.report, items=list(self.report.items)),
            replace(self.report, catalog_rows=[ROOT]),
            replace(self.report, items=(replace(self.item, references=[self.reference]),)),
            self.with_reference(replace(self.reference, reasons=["future_reason"])),
            self.with_reference(replace(self.reference, identity=list(self.reference.identity))),
            self.with_reference(replace(self.reference, identity=(["source_id", "mutable"],))),
            replace(self.report, catalog_rows=(replace(ROOT, path=list(ROOT.path)),)),
        )
        for number, report in enumerate(malformed):
            with self.subTest(case=number):
                self.assert_rejected(report)

    def test_sha_and_record_types_are_checked_before_projection(self):
        malformed = (
            replace(self.report, payload_sha256="A" * 64),
            replace(self.report, payload_sha256=73),
            replace(self.report, trusted_binding=None),
            replace(self.report, items=(object(),)),
            self.with_reference(replace(self.reference, status="VERIFIED")),
            self.with_reference(replace(self.reference, evidence=False)),
            self.with_reference(replace(self.reference, source=None)),
            replace(self.report, catalog_rows=(replace(ROOT, edition_id=True),)),
        )
        for number, report in enumerate(malformed):
            with self.subTest(case=number):
                self.assert_rejected(report)

    def test_ordinals_cannot_be_boolean_duplicate_or_out_of_sequence(self):
        malformed = (
            replace(self.report, items=(replace(self.item, row_ordinal=True),)),
            replace(self.report, items=(replace(self.item, row_ordinal=2),)),
            replace(self.report, items=(self.item, self.item)),
            self.with_reference(replace(self.reference, reference_ordinal=True)),
            self.with_reference(replace(self.reference, reference_ordinal=2)),
            replace(self.report, items=(replace(self.item,
                    references=(self.reference, self.reference)),)),
        )
        for number, report in enumerate(malformed):
            with self.subTest(case=number):
                self.assert_rejected(report)

    def test_identity_pairs_cannot_silently_collapse_or_retain_mutable_values(self):
        for identity in (
            (("source_id", "first"), ("source_id", "last")),
            (("source_id", ["mutable"]),),
            (("source_id", float("nan")),),
            ((True, "not-a-text-key"),),
        ):
            with self.subTest(identity=repr(identity)):
                self.assert_rejected(self.with_reference(replace(self.reference, identity=identity)))

    def test_source_slices_require_exact_utf8_byte_spans_and_containment(self):
        source = self.reference.source
        malformed = (
            replace(source, start=True),
            replace(source, end=source.end + 1),
            replace(source, start=source.start + 1, end=source.end + 1),
            replace(source, text="x" * len(source.text)),
            replace(source, start=-1, end=len(source.text.encode()) - 1),
        )
        for number, altered in enumerate(malformed):
            with self.subTest(case=number):
                self.assert_rejected(self.with_reference(replace(self.reference, source=altered)))
        # Item positions also cannot overlap or move backwards within a report.
        second = replace(self.item, row_ordinal=2)
        self.assert_rejected(replace(self.report, items=(self.item, second)))

    def test_surrogate_text_is_rejected_at_both_boundaries_without_normalization(self):
        malformed = (
            self.with_reference(replace(self.reference, reasons=("future\ud800",))),
            self.with_reference(replace(self.reference,
                source=replace(self.reference.source, text="\ud800"))),
            replace(self.report, catalog_rows=(replace(ROOT, heading_title="\ud800"),)),
            self.with_reference(replace(self.reference,
                evidence=replace(ROOT, path=("\ud800",)))),
        )
        for number, report in enumerate(malformed):
            with self.subTest(case=number):
                self.assert_rejected(report)

    def test_unknown_reasons_and_conflicting_catalog_order_remain_exact(self):
        reasons = ("future_reason_ث", "identity_not_found", "future_reason_ث")
        reference = replace(self.reference, status=c.ReferenceStatus.UNVERIFIED,
                            reasons=reasons, identity=(), evidence=None)
        rows = (replace(ROOT, printed_page=-1), ROOT, ROOT)
        report = replace(self.with_reference(reference), catalog_rows=rows)
        output = report.to_payload()
        self.assertEqual(output["items"][0]["references"][0]["reasons"], list(reasons))
        self.assertEqual([row["printed_page"] for row in output["asserted_catalog"]], [-1, 7, 7])
        first = report.json_bytes()
        output["items"][0]["references"][0]["reasons"].append("changed")
        self.assertEqual(report.json_bytes(), first)


if __name__ == "__main__":
    unittest.main()
