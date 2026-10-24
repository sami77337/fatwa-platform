"""Offline reconciliation counts, original contracts, byte receipts and recovery."""

import base64
import hashlib
import json
import socket
import sqlite3
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline.batches import PreparedInput, prepare_batches
from apps.prepared_pipeline.diagnostics import diagnose_batches
from tests.prepared_pipeline.test_file_flow import file_bytes, row


def source(identity, *rows, suffix=".json"):
    return PreparedInput(identity, file_bytes(list(rows), suffix), suffix)


class DiagnosticTests(unittest.TestCase):
    def test_committed_synthetic_workflow_reconciles_known_fixture_identities(self):
        root = Path(__file__).resolve().parents[2] / "tools/content_intake/examples"
        fixtures = [
            PreparedInput("a", (root / "synthetic-batch-a.csv").read_bytes(), ".csv"),
            PreparedInput("b", (root / "synthetic-batch-b.jsonl").read_bytes(), ".jsonl"),
        ]
        report = self.diagnose(
            *fixtures, available_source_ids=["synthetic-source-a"], expected_batch_ids=["a", "b"]
        ).report
        self.assertEqual(report["summary"]["record_count"], 4)
        self.assertEqual(report["summary"]["draft_count"], 1)
        self.assertEqual(report["summary"]["status_counts"]["blocked-invalid"], 3)
        self.assertEqual(report["summary"]["cross_batch_duplicate_group_count"], 1)
        self.assertEqual(report["summary"]["diagnostic_counts"]["missing_source"], 1)
        self.assertEqual(
            [entry["input_sha256"] for entry in report["inputs"]],
            [hashlib.sha256(fixture.raw).hexdigest() for fixture in fixtures],
        )

    def diagnose(self, *inputs, **options):
        return diagnose_batches(inputs, synthetic_fixtures_only=True, **options)

    def test_every_format_preserves_bytes_text_offsets_and_original_preparation_reports(self):
        for suffix in (".csv", ".json", ".jsonl"):
            with self.subTest(suffix=suffix):
                original = source("a", row(), row("bad", question=""), suffix=suffix)
                result = self.diagnose(original)
                report = result.report
                baseline = prepare_batches([original], synthetic_fixtures_only=True)
                self.assertEqual(
                    [r["preparation"] for r in report["rows"]],
                    json.loads(baseline.batches[0].batch.json_bytes())["items"],
                )
                self.assertEqual(base64.b64decode(report["inputs"][0]["raw_base64"]), original.raw)
                for report_row in report["rows"]:
                    span = report_row["provenance"]
                    self.assertEqual(span["input_sha256"], hashlib.sha256(original.raw).hexdigest())
                    self.assertEqual(
                        base64.b64decode(span["raw_base64"]),
                        original.raw[span["byte_start"] : span["byte_end"]],
                    )
                self.assertEqual(
                    report["rows"][0]["preparation"]["original"]["question"], row()["question"]
                )
                self.assertTrue(result.has_errors)

    def test_cross_batch_duplicate_groups_link_all_rows_without_repeating_member_lists(self):
        a = source("a", row("same"), row("same", question=""))
        b = source("b", row("same"), row("unique"))
        report = self.diagnose(a, b).report
        (group,) = report["duplicate_groups"]
        self.assertTrue(group["cross_batch"])
        self.assertEqual(len(group["locations"]), 3)
        self.assertEqual(report["summary"]["status_counts"]["blocked-invalid"], 3)
        self.assertEqual(report["summary"]["draft_count"], 1)
        for item in report["rows"][:3]:
            self.assertIn("duplicate_id", [f["code"] for f in item["diagnostics"]])
            (issue,) = [f for f in item["diagnostics"] if f["code"] == "duplicate_id"]
            self.assertEqual(issue["group_id"], group["group_id"])
            self.assertNotIn("locations", issue)

    def test_row_identity_stable_across_reordering_and_identical_file_aliases(self):
        a, b = source("a", row("a")), source("b", row("b"))
        first = self.diagnose(a, b).report
        second = self.diagnose(b, a).report
        self.assertEqual(first["rows"][0]["row_id"], second["rows"][1]["row_id"])
        aliases = self.diagnose(a, PreparedInput("alias", a.raw, a.suffix)).report
        self.assertEqual(aliases["rows"][0]["row_id"], aliases["rows"][1]["row_id"])
        self.assertNotEqual(aliases["rows"][0]["batch_id"], aliases["rows"][1]["batch_id"])
        self.assertEqual(len(aliases["duplicate_groups"][0]["locations"]), 2)

    def test_missing_sources_are_exact_and_never_become_trusted_mappings(self):
        original = source(
            "a",
            row(
                reference_links=[
                    {"source_id": "مَصدر", "heading_id": "h"},
                    {"source_id": "مصدر", "heading_id": "h2"},
                ]
            ),
        )
        result = self.diagnose(original, available_source_ids=["مَصدر"])
        (item,) = result.report["rows"]
        (missing,) = [f for f in item["diagnostics"] if f["code"] == "missing_source"]
        self.assertEqual((missing["source_id"], missing["reference_index"]), ("مصدر", 2))
        self.assertEqual(item["preparation"]["draft"]["intake"]["reference_links"], [])
        self.assertTrue(
            all(r["outcome"] == "unverified" for r in item["preparation"]["references"])
        )
        self.assertFalse(result.report["inventory"]["establishes_reference_trust"])
        self.assertFalse(result.has_errors)  # Source issues require human review.

    def test_unknown_and_explicit_empty_inventory_are_distinct(self):
        original = source("a", row(reference_links=[{"source_id": "s", "heading_id": "h"}]))
        unknown = self.diagnose(original).report
        empty = self.diagnose(original, available_source_ids=[]).report
        self.assertEqual(
            unknown["summary"]["diagnostic_counts"]["source_inventory_not_supplied"], 1
        )
        self.assertNotIn("missing_source", unknown["summary"]["diagnostic_counts"])
        self.assertEqual(empty["summary"]["diagnostic_counts"]["missing_source"], 1)

    def test_blocked_rows_still_have_independent_source_diagnostics(self):
        original = source(
            "a", row(question="", reference_links=[{"source_id": "missing", "heading_id": "h"}])
        )
        report = self.diagnose(original, available_source_ids=[]).report
        self.assertEqual(report["summary"]["diagnostic_counts"]["missing_source"], 1)
        self.assertIn("required", report["summary"]["diagnostic_counts"])

    def test_malformed_source_retains_full_bytes_and_valid_files_continue(self):
        raw = b"\xff{invalid synthetic bytes"
        result = self.diagnose(
            PreparedInput("bad", raw, ".json"),
            source("ok", row()),
            expected_batch_ids=["bad", "ok", "missing"],
        )
        report = result.report
        self.assertEqual(report["summary"]["error_count"], 1)
        self.assertEqual(report["summary"]["record_count"], 1)
        self.assertEqual(base64.b64decode(report["inputs"][0]["raw_base64"]), raw)
        self.assertEqual(report["inputs"][0]["input_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["collection_diagnostics"][0]["batch_id"], "missing")
        self.assertTrue(result.has_errors)

    def test_summary_counts_are_recomputed_from_exact_original_row_reports(self):
        report = self.diagnose(
            source("a", row("same"), row("bad", question="")),
            source("b", row("same"), row("review", prepared_clip_url="")),
        ).report
        rows = report["rows"]
        summary = report["summary"]
        self.assertEqual(summary["record_count"], len(rows))
        self.assertEqual(
            summary["draft_count"], sum(r["preparation"]["draft"] is not None for r in rows)
        )
        for status, count in summary["status_counts"].items():
            self.assertEqual(count, sum(status in r["preparation"]["statuses"] for r in rows))
        self.assertEqual(
            summary["finding_counts"],
            dict(Counter(f["code"] for r in rows for f in r["preparation"]["findings"])),
        )
        self.assertEqual(
            summary["diagnostic_counts"],
            dict(Counter(f["code"] for r in rows for f in r["diagnostics"])),
        )
        self.assertEqual(summary["diagnostic_row_count"], sum(bool(r["diagnostics"]) for r in rows))
        self.assertEqual(
            summary["reference_counts"],
            dict(Counter(ref["outcome"] for r in rows for ref in r["preparation"]["references"])),
        )

    def test_deterministic_exports_manifest_and_detached_report(self):
        original = source("a", row())
        result = self.diagnose(original)
        expected = result.artifacts()
        self.assertEqual(expected, self.diagnose(original).artifacts())
        self.assertEqual(json.loads(expected["rows.jsonl"]), result.report["rows"][0])
        manifest = json.loads(expected["manifest.json"])
        for name, metadata in manifest["outputs"].items():
            self.assertEqual(
                metadata,
                dict(bytes=len(expected[name]), sha256=hashlib.sha256(expected[name]).hexdigest()),
            )
        detached = result.report
        detached["rows"][0]["preparation"]["original"]["question"] = "changed"
        self.assertEqual(result.artifacts(), expected)
        self.assertIn("الدفعة a، الصف 1", result.preview_ar())
        for issue in result.report["rows"][0]["diagnostics"]:
            self.assertTrue(any("\u0600" <= c <= "\u06ff" for c in issue["recovery_ar"]))

    def test_bounds_and_guard_stop_unbounded_generators(self):
        for value in (False, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                diagnose_batches([], synthetic_fixtures_only=value)
        for option in ("available_source_ids", "expected_batch_ids"):

            def ids():
                yield from map(str, range(1001))
                self.fail("consumed beyond bound")

            with self.subTest(option=option), self.assertRaises(ValidationError):
                self.diagnose(**{option: ids()})
            for values in (["same", "same"], ["x" * 101], [" id "], ["\ud800"]):
                with (
                    self.subTest(option=option, values=repr(values)),
                    self.assertRaises(ValidationError),
                ):
                    self.diagnose(**{option: values})
        with self.assertRaises(ValidationError):
            self.diagnose(
                source("a", *[row(str(i)) for i in range(501)]),
                source("b", *[row(str(i)) for i in range(501, 1001)]),
            )

    def test_export_bound_fails_closed(self):
        with patch("apps.prepared_pipeline.diagnostics.MAX_EXPORT_BYTES", 10):
            with self.assertRaisesRegex(ValidationError, "export_byte_limit_exceeded"):
                self.diagnose(source("a", row()))
        result = self.diagnose(source("a", row()))
        with patch("apps.prepared_pipeline.diagnostics.MAX_EXPORT_BYTES", len(result.json_bytes())):
            with self.assertRaisesRegex(ValidationError, "export_byte_limit_exceeded"):
                result.artifacts()

    def test_row_navigation_shows_duplicate_destinations_and_rejects_unknown_rows(self):
        result = self.diagnose(source("a", row("dup"), row("other")), source("b", row("dup")))
        preview = result.preview_ar(batch_id="a", row_number=1)
        self.assertIn("مجموعة التكرار", preview)
        self.assertIn("الدفعة b، الصف 1", preview)
        self.assertNotIn("الدفعة a، الصف 2", preview)
        for options in (
            dict(batch_id="missing", row_number=1),
            dict(batch_id="a", row_number=0),
            dict(batch_id="a", row_number=True),
            dict(row_number=1),
        ):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                result.preview_ar(**options)

    def test_offline_only_and_hold_markers(self):
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network")),
            patch.object(sqlite3, "connect", side_effect=AssertionError("database")),
        ):
            result = self.diagnose(source("a", row()))
        self.assertEqual(result.report["gates"], dict(B="NOT_PASSED", C="HOLD", D="HOLD", E="HOLD"))
        self.assertEqual(result.report["deployment"], "NOT_DEPLOYED")
        self.assertFalse(result.report["source_modification_performed"])
