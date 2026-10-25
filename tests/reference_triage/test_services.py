"""Projection must retain existing service decisions and source occurrences."""

from dataclasses import asdict
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench.services import build_cases, build_prepared_workbench


class InvestigationTests(SimpleTestCase):
    def test_existing_fixed_cases_and_batches_are_preserved_without_writes(self):
        from apps.reference_triage.services import build_investigation

        originals = (*build_cases(), *build_prepared_workbench().cases)
        before = tuple(asdict(case) for case in originals)
        report = build_investigation()
        self.assertEqual(tuple(asdict(row.case) for row in report.cases), before)
        self.assertEqual(len(report.cases), 20)
        self.assertEqual(len(report.batches), 6)
        self.assertEqual(report.summary.records, 20)
        self.assertEqual(report.summary.references, sum(len(c.references) for c in originals))
        for row, original in zip(report.cases, originals, strict=True):
            self.assertEqual(row.source_sha256, sha256(original.raw_source.encode()).hexdigest())
            self.assertEqual(row.summary.references, len(original.references))
            for reference, raw in zip(row.references, original.references, strict=True):
                self.assertEqual(reference.raw_status, raw["status"])
                self.assertEqual(reference.source_text, raw["source"]["text"])
                self.assertEqual(reference.reasons, tuple(raw["reasons"]))
                self.assertEqual(
                    reference.source_sha256, sha256(raw["source"]["text"].encode()).hexdigest()
                )

    def test_summary_is_exclusive_per_reference_and_keeps_empty_rows_and_failed_batch(self):
        from apps.reference_triage.services import build_investigation

        report = build_investigation()
        summary = report.summary
        self.assertEqual(
            summary.references, summary.verified + summary.unresolved + summary.mismatched
        )
        self.assertGreater(summary.verified, 0)
        self.assertGreater(summary.unresolved, 0)
        # The existing fixed fixtures have no mismatches: do not invent one.
        self.assertEqual(summary.mismatched, 0)
        self.assertEqual(summary.missing, sum(not row.references for row in report.cases))
        self.assertEqual(sum(b.summary.records for b in report.batches), summary.records)
        self.assertEqual(sum(b.summary.references for b in report.batches), summary.references)
        failed = next(b for b in report.batches if b.batch_id == "synthetic-malformed")
        self.assertTrue(failed.error_code)
        self.assertTrue(failed.recovery)
        self.assertEqual(failed.summary.records, 0)
        self.assertEqual(failed.summary.verified, 0)

    def test_presentation_does_not_invent_evidence_or_normalize_arabic_or_identity(self):
        import json

        from apps.reference_triage.services import build_investigation

        report = build_investigation()
        for row in report.cases:
            for reference, raw in zip(row.references, row.case.references, strict=True):
                self.assertEqual(
                    json.loads(reference.original_identity), raw.get("original_identity", {})
                )
                self.assertEqual(json.loads(reference.verified_identity), raw["verified_identity"])
                self.assertEqual(json.loads(reference.evidence), raw["evidence"])
                self.assertEqual(reference.explanation, raw["explanation_ar"])
                self.assertTrue(reference.recovery)
        csv = next(row for row in report.cases if row.case.key == "batch-synthetic-csv-1")
        self.assertEqual(csv.case.question, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")

    def test_unknown_service_status_fails_closed_without_reclassifying_it(self):
        from dataclasses import replace

        from apps.editorial_workbench.services import WorkbenchDataError
        from apps.reference_triage import services

        case = build_cases()[0]
        bad = replace(case, references=({**case.references[0], "status": "approved"},))
        with patch.object(services, "build_cases", return_value=(bad,)):
            with self.assertRaises(WorkbenchDataError):
                services.build_investigation()

    def test_mismatch_projection_retains_both_service_vocabularies_and_no_evidence(self):
        from dataclasses import replace

        from apps.reference_triage import services

        case = build_cases()[0]
        for status in ("mismatched", "mismatched_metadata"):
            raw = {**case.references[0], "status": status, "reasons": ["source_identity_mismatch"]}
            with patch.object(
                services, "build_cases", return_value=(replace(case, references=(raw,)),)
            ):
                row = services.build_investigation().cases[0]
            self.assertEqual(row.summary.mismatched, 1)
            self.assertEqual(row.summary.verified, 0)
            self.assertEqual(row.references[0].raw_status, status)
            self.assertEqual(row.references[0].evidence, "null")
