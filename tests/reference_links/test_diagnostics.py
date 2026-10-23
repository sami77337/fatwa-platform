"""Focused pure reports over fixed Wave7 synthetic contracts; no owner sources."""

import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from apps.intake_workflow import contracts as c, fixtures
from apps.reference_links.resolution import Heading


ROOT = Heading(
    7001, 1, "مرجع اصطناعي لتجارب Wave7", "كِتَابٌ اصطناعي", "الأول", 7,
    ("كِتَابٌ اصطناعي",), c.SOURCE_IDENTITY["source_namespace"], "622",
    c.SOURCE_IDENTITY["source_input_sha256"], c.SOURCE_IDENTITY["edition_key"],
    c.SOURCE_IDENTITY["source_archive_sha256"],
)
C1 = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}
C2 = {**c.SOURCE_IDENTITY, "source_id": "wave7-title-1"}


def payload(links):
    return json.dumps({"schema": c.PAYLOAD_SCHEMA, "synthetic_fixtures_only": True,
                       "items": [{"reference_links": links}]},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ReferenceDiagnosticsTests(unittest.TestCase):
    def report(self, raw=None, rows=(ROOT,)):
        from apps.reference_links.diagnostics import build_reference_diagnostics

        return build_reference_diagnostics(
            payload([C1]) if raw is None else raw,
            synthetic_fixtures_only=True, catalog_rows=rows,
        )

    def test_three_labels_preserve_contract_results_and_exact_bindings(self):
        raw = payload([C1, {"source_id": "7001", "heading_id": "1"},
                       {**C2, "edition_key": "other-edition"}])
        output = self.report(raw).to_payload()
        references = output["items"][0]["references"]
        self.assertEqual([r["status"] for r in references],
                         ["verified", "unresolved", "mismatched"])
        self.assertEqual([r["contract_status"] for r in references],
                         ["VERIFIED", "UNVERIFIED", "MISMATCHED"])
        self.assertEqual(output["summary"], {"verified": 1, "unresolved": 1, "mismatched": 1})
        self.assertEqual(references[0]["verified_identity"], dict(c.VERIFIED_IDENTITIES[0]))
        self.assertEqual(references[0]["evidence"]["path"], ["كِتَابٌ اصطناعي"])
        self.assertEqual(output["trusted_binding"]["edition"]["identity"], dict(c.SOURCE_IDENTITY))
        self.assertEqual(output["trusted_binding"]["headings"][0], {
            "c1_source_id": "W7-SOURCE", "c1_heading_id": "W7-HEADING-1",
            "c2_source_id": "wave7-title-1", "source_row_id": 1,
        })
        self.assertEqual(references[1]["reasons"], ["explicit_mapping_missing"])
        self.assertEqual(references[2]["reasons"], ["source_identity_mismatch"])
        for ref in references:
            source = ref["source"]
            exact = raw[source["start"]:source["end"]]
            self.assertEqual(exact, source["text"].encode("utf-8"))
            self.assertEqual(ref["source_sha256"], hashlib.sha256(exact).hexdigest())
            self.assertNotIn("citation", ref)
            self.assertNotIn("citation_text", ref)
        for ref in references[1:]:
            self.assertEqual(ref["verified_identity"], {})
            self.assertIsNone(ref["evidence"])

    def test_every_c2_identity_field_remains_exact_on_mismatch(self):
        for name in C2:
            altered = {**C2, name: C2[name] + "-changed"}
            with self.subTest(field=name):
                ref = self.report(payload([altered])).to_payload()["items"][0]["references"][0]
                self.assertEqual(ref["status"], "mismatched")
                self.assertEqual(json.loads(ref["source"]["text"]), altered)
                self.assertEqual(ref["verified_identity"], {})
                self.assertIsNone(ref["evidence"])

    def test_absent_ambiguous_and_wrong_edition_snapshots_stay_unresolved(self):
        for rows, reason in (((), "identity_not_found"),
                             ((ROOT, ROOT), "multiple_exact_candidates"),
                             ((replace(ROOT, edition_id=7002),), "identity_not_found")):
            with self.subTest(reason=reason, rows=len(rows)):
                output = self.report(rows=rows).to_payload()
                ref = output["items"][0]["references"][0]
                self.assertEqual(ref["status"], "unresolved")
                self.assertEqual(ref["reasons"], [reason])
                self.assertIsNone(ref["evidence"])
                self.assertEqual(ref["verified_identity"], {})
                self.assertEqual(len(output["asserted_catalog"]), len(rows))

    def test_conflicting_snapshot_pins_are_retained_without_verified_evidence(self):
        for name, value in (("source_namespace", "different-synthetic-namespace"),
                            ("source_book_id", "623"), ("edition_key", "another-edition"),
                            ("source_archive_sha256", "c" * 64),
                            ("source_input_sha256", "d" * 64), ("printed_page", 99)):
            with self.subTest(field=name):
                output = self.report(rows=(replace(ROOT, **{name: value}),)).to_payload()
                ref = output["items"][0]["references"][0]
                self.assertEqual(ref["status"], "mismatched")
                self.assertEqual(ref["reasons"], ["catalog_metadata_mismatch"])
                self.assertIsNone(ref["evidence"])
                self.assertEqual(output["asserted_catalog"][0][name], value)

    def test_lossless_invalid_pointers_and_duplicate_slices_are_unresolved(self):
        raw = (b'{"schema":"' + c.PAYLOAD_SCHEMA.encode() +
               b'","synthetic_fixtures_only":true,"items":[{"reference_links":['
               b'{ "source_id":"W7-SOURCE","heading_id":"W7-HEADING-1" },'
               b'{"heading_id":"W7-HEADING-1", "source_id":"W7-SOURCE"},'
               b'{"source_id":73.000000000000001},1e-20000,null]}]}')
        output = self.report(raw).to_payload()
        refs = output["items"][0]["references"]
        self.assertEqual([ref["status"] for ref in refs], ["unresolved"] * 5)
        self.assertEqual([ref["reasons"] for ref in refs[:2]], [["duplicate_pointer"]] * 2)
        self.assertNotEqual(refs[0]["source"]["text"], refs[1]["source"]["text"])
        self.assertEqual(refs[2]["source"]["text"], '{"source_id":73.000000000000001}')
        self.assertEqual(refs[3]["source"]["text"], "1e-20000")
        for ref in refs:
            source = ref["source"]
            self.assertEqual(raw[source["start"]:source["end"]], source["text"].encode())
        self.assertEqual(output["input_sha256"], hashlib.sha256(raw).hexdigest())

    def test_report_is_deterministic_immutable_and_has_explicit_limits(self):
        raw = fixtures.synthetic_payload()
        report = self.report(raw)
        first = report.json_bytes()
        self.assertEqual(first, self.report(raw).json_bytes())
        self.assertEqual(json.loads(first), report.to_payload())
        self.assertTrue(first.endswith(b"\n"))
        output = report.to_payload()
        self.assertEqual(output["schema"], "fatwa.reference-diagnostics.v1")
        self.assertEqual(output["source_config_id"], c.SOURCE_CONFIG_ID)
        self.assertTrue(output["synthetic_only"])
        self.assertFalse(output["archive_inspected"])
        self.assertFalse(output["scholarly_verified"])
        self.assertEqual(output["verification_scope"], "asserted_fixed_synthetic_toc_snapshot_only")
        self.assertEqual(output["gates"], {"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"})
        self.assertEqual(output["phase01"], "BLOCKED")
        self.assertEqual(output["scope_status"], "SCOPE_DEVIATION_HOLD")
        self.assertEqual(output["deployment_status"], "NOT_DEPLOYED/GATES_HOLD")
        self.assertEqual(output["summary"], {"verified": 2, "unresolved": 1, "mismatched": 0})
        output["items"][0]["references"][0]["verified_identity"]["source_id"] = "mutated"
        output["trusted_binding"]["edition"]["identity"]["edition_key"] = "mutated"
        self.assertEqual(report.json_bytes(), first)
        with self.assertRaises(FrozenInstanceError):
            report.payload_sha256 = "mutated"

    def test_existing_legacy_evidence_is_not_filled_in_by_report(self):
        legacy = replace(ROOT, edition_key=None, source_archive_sha256=None)
        output = self.report(rows=(legacy,)).to_payload()
        ref = output["items"][0]["references"][0]
        self.assertEqual(ref["status"], "verified")
        self.assertIsNone(ref["evidence"]["edition_key"])
        self.assertIsNone(ref["evidence"]["source_archive_sha256"])
        self.assertEqual(ref["verified_identity"], dict(c.VERIFIED_IDENTITIES[0]))
        self.assertFalse(output["archive_inspected"])

    def test_acknowledgement_and_immutable_snapshot_contracts_are_required(self):
        from apps.reference_links.diagnostics import build_reference_diagnostics

        for ack in (False, None, 1):
            with self.subTest(ack=ack), self.assertRaisesRegex(c.ContractError, "synthetic_acknowledgement_required"):
                build_reference_diagnostics(object(), synthetic_fixtures_only=ack)
        for rows in ([ROOT], (object(),)):
            with self.subTest(rows=type(rows)), self.assertRaisesRegex(c.ContractError, "explicit_heading_snapshot_required"):
                self.report(rows=rows)

    def test_mutable_heading_fields_cannot_change_a_report_after_building(self):
        for changes in ({"path": ["كِتَابٌ اصطناعي"]}, {"work_title": ["mutable"]},
                        {"printed_part": {"mutable": "part"}}, {"printed_page": [7]},
                        {"edition_key": {"mutable": "edition"}}):
            with self.subTest(fields=tuple(changes)), self.assertRaisesRegex(
                c.ContractError, "immutable_heading_fields_required"
            ):
                self.report(rows=(replace(ROOT, **changes),))

    def test_report_does_not_open_files_network_or_database(self):
        from django.db.backends.base.base import BaseDatabaseWrapper

        # Warm only pure contract imports before blocking any attempted I/O.
        fixtures.trusted_reference_map()
        from apps.reference_links.diagnostics import build_reference_diagnostics

        raw = payload([C1])
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
             patch("socket.socket", side_effect=AssertionError("network I/O")), \
             patch.object(BaseDatabaseWrapper, "connect", side_effect=AssertionError("DB connect")), \
             patch.object(BaseDatabaseWrapper, "cursor", side_effect=AssertionError("DB query")):
            report = build_reference_diagnostics(raw, synthetic_fixtures_only=True, catalog_rows=(ROOT,))
            output = json.loads(report.json_bytes())
        self.assertEqual(output["summary"], {"verified": 1, "unresolved": 0, "mismatched": 0})


class ArabicReferenceExplanationTests(unittest.TestCase):
    report = ReferenceDiagnosticsTests.report

    def test_arabic_status_explanations_preserve_planner_fields(self):
        from dataclasses import asdict
        from apps.intake_workflow.references import plan_reference_verification

        raw = payload([C1, {"source_id": "7001", "heading_id": "1"},
                       {**C2, "edition_key": "other-edition"}])
        report = self.report(raw)
        planned = plan_reference_verification(raw, synthetic_fixtures_only=True, catalog_rows=(ROOT,))
        refs = report.to_payload()["items"][0]["references"]
        expected = ["تطابق تقني مع لقطة الفهرس الاصطناعية المصرح بها فقط.",
                    "لم يثبت تطابق تقني مع لقطة الفهرس الاصطناعية المصرح بها.",
                    "تعارض تقني مع بيانات الربط أو الفهرس الاصطناعية المصرح بها."]
        for ref, original, text in zip(refs, planned[0].references, expected, strict=True):
            self.assertRegex(ref["explanation_ar"], r"[؀-ۿ]")
            self.assertNotIn("?", ref["explanation_ar"])
            self.assertEqual(ref["explanation_ar"], text)
            self.assertEqual(ref["verification_limit_ar"],
                             "لا تثبت هذه النتيجة صحة علمية أو ملاءمة إحالة، ولا تعني فحص الأرشيف.")
            self.assertEqual(ref["source"], asdict(original.source))
            self.assertEqual(ref["verified_identity"], dict(original.identity))
            self.assertEqual(ref["reasons"], list(original.reasons))
            self.assertEqual(ref["source_sha256"], hashlib.sha256(
                raw[original.source.start:original.source.end]).hexdigest())
        self.assertEqual(refs[0]["reason_explanations_ar"], [])
        self.assertEqual(refs[1]["reason_explanations_ar"],
                         ["لا يوجد ربط صريح للمؤشر في الإعداد الاصطناعي الثابت."])
        self.assertEqual(refs[2]["reason_explanations_ar"],
                         ["هوية المصدر المدخلة لا تطابق الهوية الاصطناعية الثابتة."])
        before = report.json_bytes()
        refs[1]["reason_explanations_ar"].append("تغيير")
        self.assertEqual(report.json_bytes(), before)

    def test_reason_explanations_follow_existing_reason_order_with_safe_fallback(self):
        report = self.report()
        original = report.items[0].references[0]
        reasons = ("identity_not_found", "multiple_exact_candidates", "future_reason")
        altered = replace(original, status=c.ReferenceStatus.UNVERIFIED, reasons=reasons,
                          identity=(), evidence=None)
        output = replace(report, items=(replace(report.items[0], references=(altered,)),)).to_payload()
        ref = output["items"][0]["references"][0]
        self.assertEqual(ref["reasons"], list(reasons))
        self.assertEqual(ref["reason_explanations_ar"], [
            "لم توجد الهوية المطلوبة في لقطة الفهرس المصرح بها.",
            "توجد عدة سجلات تطابق الهوية المطلوبة؛ لم يختر التقرير أحدها.",
            "سبب تشخيصي غير مترجم؛ يرجى الرجوع إلى رمز السبب الأصلي.",
        ])
