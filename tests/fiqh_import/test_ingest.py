"""Synthetic fixtures only; these tests cannot attest to the original 11,397 titles."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.fiqh_import.ingest import (
    ImportResult,
    IngestError,
    ValidationError,
    canonical_json,
    ingest,
    load_manifest,
    write_export,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPOSITORY = Path(__file__).resolve().parents[2]


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).parent / ".scratch"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.rows = json.loads((FIXTURES / "synthetic-five-level.json").read_text(encoding="utf-8"))
        self.manifest = load_manifest(FIXTURES / "synthetic-five-level.manifest.json")

    def source(self, rows=None, file_format="json", *, raw=None):
        if rows is None:
            rows = self.rows
        if raw is None:
            if file_format == "json":
                raw = json.dumps(rows, ensure_ascii=False).encode("utf-8")
            elif file_format == "jsonl":
                raw = b"".join(canonical_json(row) for row in rows)
            else:
                fields = list(dict.fromkeys(key for row in rows for key in row))
                text = io.StringIO(newline="")
                writer = csv.DictWriter(text, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
                raw = text.getvalue().encode("utf-8")
        source = self.directory / f"source.{file_format}"
        source.write_bytes(raw)
        manifest = replace(self.manifest, input_sha256=hashlib.sha256(raw).hexdigest())
        return source, manifest

    def result(self, rows=None, **options):
        source, manifest = self.source(rows)
        return ingest(source, manifest, profile="synthetic", **options)

    def codes(self, rows=None, **options):
        result = self.result(rows, strict=False, **options)
        self.assertFalse(result.report["valid"])
        self.assertIsNone(result.output_bytes)
        return {issue["code"] for issue in result.report["issues"]}

    def cli(self, source, manifest, *arguments):
        manifest_path = self.directory / "manifest.json"
        manifest_path.write_bytes(canonical_json(manifest.__dict__))
        command = [sys.executable, "-B", "-m", "tools.fiqh_import", "--input", str(source),
                   "--manifest", str(manifest_path), "--profile", "synthetic", *map(str, arguments)]
        return subprocess.run(command, cwd=REPOSITORY, capture_output=True, check=False)

    def test_checked_in_fixture_identity_and_five_level_tree(self):
        source = FIXTURES / "synthetic-five-level.json"
        result = ingest(source, self.manifest, profile="synthetic")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), self.manifest.input_sha256)
        self.assertTrue(result.report["valid"])
        self.assertEqual((result.report["unique_valid_records"], result.report["roots"],
                          result.report["max_depth"], result.report["reachable_nodes"]), (7, 2, 5, 7))
        self.assertEqual((result.report["direct_titles"], result.report["inferred_titles"]), (6, 1))
        self.assertEqual(result.report["real_source_acceptance"], "NOT_RUN")
        self.assertEqual(result.report["source_status"], "SYNTHETIC_ONLY_SOURCE_DATA_MISSING")

    def test_reruns_are_byte_identical_with_matching_hashes(self):
        source, manifest = self.source()
        first = ingest(source, manifest, profile="synthetic")
        second = ingest(source, manifest, profile="synthetic")
        self.assertEqual(first.output_bytes, second.output_bytes)
        self.assertEqual(canonical_json(first.report), canonical_json(second.report))
        self.assertEqual(hashlib.sha256(first.output_bytes).hexdigest(), first.report["output_sha256"])
        self.assertTrue(first.output_bytes.endswith(b"\n"))
        self.assertNotIn(b"\r\n", first.output_bytes)
        self.assertFalse(first.output_bytes.startswith(b"\xef\xbb\xbf"))

    def test_preserves_original_text_ids_pages_edition_and_provenance(self):
        result = self.result()
        exported = {row["source_id"]: row for row in map(json.loads, result.output_bytes.splitlines())}
        row = exported["chapter"]
        self.assertEqual(row["title"], self.rows[2]["title"])
        self.assertEqual(row["search_title"], "باب اجارة اصطناعي")
        self.assertEqual((row["parent_id"], row["source_part"], row["source_page"]), ("book", "01", "007"))
        self.assertEqual((row["part"], row["page"]), (1, 7))
        self.assertEqual(exported["sibling"]["edition"], self.rows[-1]["edition"])
        self.assertEqual(exported["sibling"]["provenance"], self.rows[-1]["provenance"])
        self.assertEqual(row["edition"], self.manifest.edition)
        self.assertEqual(exported["leaf"]["inference_evidence"], self.rows[5]["inference_evidence"])

    def test_unsorted_input_exports_parent_first_in_sibling_order(self):
        result = self.result(list(reversed(self.rows)))
        self.assertFalse(result.report["input_topological"])
        self.assertTrue(result.report["output_topological"])
        output = list(map(json.loads, result.output_bytes.splitlines()))
        self.assertEqual([r["source_id"] for r in output],
                         ["intro", "book", "chapter", "section", "branch", "leaf", "sibling"])
        seen = set()
        for sequence, row in enumerate(output, 1):
            self.assertEqual(row["sequence"], sequence)
            self.assertTrue(row["parent_id"] is None or row["parent_id"] in seen)
            seen.add(row["source_id"])

    def test_two_level_tree(self):
        rows = self.rows[:3]
        source, manifest = self.source(rows)
        manifest = replace(manifest, expected_nodes=3, expected_max_depth=2)
        result = ingest(source, manifest, profile="synthetic")
        self.assertEqual(result.report["max_depth"], 2)

    def test_csv_json_and_jsonl_support(self):
        for file_format in ("csv", "json", "jsonl"):
            with self.subTest(file_format=file_format):
                source, manifest = self.source(file_format=file_format)
                result = ingest(source, manifest, profile="synthetic")
                self.assertTrue(result.report["valid"])
                self.assertEqual(result.report["unique_valid_records"], 7)

    def test_utf8_bom_and_csv_quoted_multiline_title(self):
        self.rows[2]["title"] = 'عنوان, "اصطناعي"\nسطر ثان'
        source, manifest = self.source(file_format="csv")
        raw = b"\xef\xbb\xbf" + source.read_bytes()
        source, manifest = self.source(file_format="csv", raw=raw)
        result = ingest(source, manifest, profile="synthetic")
        row = next(r for r in map(json.loads, result.output_bytes.splitlines()) if r["source_id"] == "chapter")
        self.assertEqual(row["title"], self.rows[2]["title"])
        self.assertEqual(result.report["input_sha256"], hashlib.sha256(raw).hexdigest())

    def test_unicode_line_separator_in_jsonl_title_is_preserved(self):
        self.rows[2]["title"] = "عنوان\u2028اصطناعي"
        source, manifest = self.source(file_format="jsonl")
        result = ingest(source, manifest, profile="synthetic")
        self.assertIn(self.rows[2]["title"].encode("utf-8"), result.output_bytes)
        self.assertEqual(result.report["input_records"], 7)

    def test_cycle_and_unreachable_component(self):
        self.rows[2]["parent_id"] = "leaf"
        self.assertTrue({"CYCLE", "UNREACHABLE_NODES"} <= self.codes())

    def test_self_cycle(self):
        self.rows[5]["parent_id"] = "leaf"
        self.assertIn("CYCLE", self.codes())

    def test_orphan(self):
        self.rows[2]["parent_id"] = "missing"
        self.assertTrue({"ORPHAN_PARENT", "UNREACHABLE_NODES"} <= self.codes())

    def test_duplicate_ids(self):
        self.assertIn("DUPLICATE_ID", self.codes(self.rows + [dict(self.rows[2])]))

    def test_blank_titles(self):
        for value in ("", " \t", None):
            with self.subTest(value=value):
                self.rows[2]["title"] = value
                self.assertIn("INVALID_RECORD", self.codes())

    def test_invalid_or_missing_page_references(self):
        for field in ("part", "page"):
            for value in (None, "", "0", 0, -1, 1.5, True, "١", "1-3", "9" * 30):
                with self.subTest(field=field, value=value):
                    rows = [dict(r) for r in self.rows]
                    rows[2][field] = value
                    self.assertIn("INVALID_RECORD", self.codes(rows))
            rows = [dict(r) for r in self.rows]
            del rows[2][field]
            self.assertIn("INVALID_RECORD", self.codes(rows))

    def test_numeric_and_padded_ids_are_rejected_without_rewriting(self):
        for value in (12, " padded", "bad\nidentifier", ""):
            with self.subTest(value=value):
                self.rows[2]["id"] = value
                self.assertIn("INVALID_RECORD", self.codes())

    def test_explicit_title_origin_and_inference_evidence_required(self):
        for value in (None, "unknown", ""):
            rows = [dict(r) for r in self.rows]
            rows[2]["title_origin"] = value
            self.assertIn("INVALID_RECORD", self.codes(rows))
        del self.rows[5]["inference_evidence"]
        self.assertIn("INVALID_RECORD", self.codes())

    def test_direct_title_cannot_claim_inference_evidence(self):
        self.rows[2]["inference_evidence"] = "contradictory source claim"
        self.assertIn("INVALID_RECORD", self.codes())

    def test_duplicate_sibling_order_is_rejected(self):
        self.rows[-1]["sibling_order"] = 0
        self.assertIn("DUPLICATE_SIBLING_ORDER", self.codes())

    def test_child_cannot_claim_root_kind(self):
        self.rows[2]["root_kind"] = "fiqh_book"
        self.assertIn("INVALID_RECORD", self.codes())

    def test_unknown_fields_are_not_exported(self):
        self.rows[2]["private_question"] = "synthetic disallowed column"
        self.assertIn("INVALID_RECORD", self.codes())

    def test_partial_fixture_is_not_accepted_in_strict_or_dry_run(self):
        source, manifest = self.source(self.rows[:-1])
        with self.assertRaises(ValidationError) as caught:
            ingest(source, manifest, profile="synthetic")
        self.assertIn("NODE_COUNT", {i["code"] for i in caught.exception.report["issues"]})
        result = ingest(source, manifest, profile="synthetic", strict=False)
        self.assertFalse(result.report["valid"])
        self.assertIsNone(result.output_bytes)
        target = self.directory / "output.jsonl"
        with self.assertRaises(ValidationError):
            write_export(result, target)
        self.assertFalse(target.exists())

    def test_wrong_fixture_hash_fails_closed(self):
        source, manifest = self.source()
        result = ingest(source, replace(manifest, input_sha256="0" * 64),
                        profile="synthetic", strict=False)
        self.assertEqual(result.report["issues"][0]["code"], "INPUT_SHA256_MISMATCH")
        self.assertIsNone(result.output_bytes)

    def test_false_real_source_totals_and_synthetic_claim(self):
        source, manifest = self.source()
        for source_kind in ("synthetic", "owner_supplied"):
            with self.subTest(source_kind=source_kind):
                result = ingest(source, replace(manifest, source_kind=source_kind),
                                profile="real-622", strict=False)
                codes = {i["code"] for i in result.report["issues"]}
                self.assertTrue({"REAL_NODE_COUNT", "REAL_ROOT_COUNT", "REAL_ROOT_KINDS",
                                 "REAL_SOURCE_EXPECTATIONS"} <= codes)
                self.assertEqual(result.report["real_source_acceptance"], "NOT_PASSED")
                self.assertIsNone(result.output_bytes)
                if source_kind == "synthetic":
                    self.assertIn("SOURCE_DATA_MISSING", codes)

    def test_real_profile_cannot_be_weakened_by_manifest_expectations(self):
        source, manifest = self.source()
        result = ingest(source, replace(manifest, source_kind="owner_supplied",
                                       expected_nodes=11397, expected_roots=32,
                                       expected_max_depth=5), profile="real-622", strict=False)
        self.assertFalse(result.report["valid"])
        self.assertIn("REAL_NODE_COUNT", {i["code"] for i in result.report["issues"]})

    def test_synthetic_profile_cannot_downgrade_owner_supplied_data(self):
        source, manifest = self.source()
        result = ingest(source, replace(manifest, source_kind="owner_supplied"),
                        profile="synthetic", strict=False)
        self.assertEqual(result.report["issues"][0]["code"], "PROFILE_SOURCE_MISMATCH")

    def test_empty_input_is_rejected(self):
        self.assertIn("NODE_COUNT", self.codes([]))

    def test_long_tree_validation_does_not_use_recursive_traversal(self):
        rows = [{"id": str(i), "parent_id": str(i - 1) if i else None,
                 "title": "Synthetic heading", "sibling_order": 0,
                 "part": 1, "page": 1, "title_origin": "direct"} for i in range(1500)]
        source, manifest = self.source(rows)
        result = ingest(source, replace(manifest, expected_nodes=1500,
                                       expected_roots=1, expected_max_depth=1500), profile="synthetic")
        self.assertEqual(result.report["reachable_nodes"], 1500)

    def test_malformed_jsonl_csv_and_utf8(self):
        cases = [("json", b'{"id": "x"}'), ("json", b'[{"id":"a","id":"b"}]'),
                 ("json", b'[NaN]'), ("json", b'[{}'), ("json", b'[1]'),
                 ("jsonl", b'{}\n\n{}\n'), ("jsonl", b'\xff'),
                 ("csv", b'id,id\na,b\n'), ("csv", b'id,title\na,b\n')]
        for file_format, raw in cases:
            with self.subTest(file_format=file_format, raw=raw):
                source, manifest = self.source(file_format=file_format, raw=raw)
                with self.assertRaises(IngestError):
                    ingest(source, manifest, profile="synthetic")

    def test_csv_extra_and_missing_cells(self):
        header = b'id,parent_id,title,sibling_order,part,page,title_origin\n'
        for row in (b'a,,Title,0,1,1,direct,extra\n', b'a,,Title,0,1\n'):
            source, manifest = self.source(file_format="csv", raw=header + row)
            with self.assertRaises(IngestError):
                ingest(source, manifest, profile="synthetic")

    def test_size_and_record_limits(self):
        source, manifest = self.source()
        with patch("tools.fiqh_import.ingest.MAX_INPUT_BYTES", 10):
            with self.assertRaises(IngestError):
                ingest(source, manifest, profile="synthetic")
        with patch("tools.fiqh_import.ingest.MAX_RECORDS", 2):
            with self.assertRaises(IngestError):
                ingest(source, manifest, profile="synthetic")

    def test_manifest_validation(self):
        valid = dict(self.manifest.__dict__)
        cases = [{**valid, "book_id": "623"}, {**valid, "input_sha256": "invalid"},
                 {**valid, "edition": " "}, {**valid, "expected_roots": 8},
                 {**valid, "expected_nodes": True}, {**valid, "unexpected": "field"},
                 {**valid, "source_kind": "unknown"}]
        target = self.directory / "invalid-manifest.json"
        for data in cases:
            with self.subTest(data=data):
                target.write_bytes(canonical_json(data))
                with self.assertRaises(IngestError):
                    load_manifest(target)

    def test_direct_api_rejects_invalid_manifest(self):
        source, manifest = self.source()
        for changes in ({"book_id": "other-book"}, {"expected_nodes": "7"},
                        {"input_sha256": "unpinned"}, {"source_kind": "unknown"}):
            with self.subTest(changes=changes):
                with self.assertRaises(IngestError):
                    ingest(source, replace(manifest, **changes), profile="synthetic")

    def test_atomic_export_is_idempotent(self):
        result = self.result()
        target = self.directory / "export.jsonl"
        write_export(result, target)
        self.assertEqual(target.read_bytes(), result.output_bytes)
        write_export(result, target)
        self.assertEqual(target.read_bytes(), result.output_bytes)
        self.assertEqual(list(self.directory.glob(".export.jsonl.*")), [])

    def test_hash_mutation_is_rejected_before_writing(self):
        result = self.result()
        target = self.directory / "export.jsonl"
        corrupted = ImportResult(result.report, result.output_bytes + b"tampering")
        with self.assertRaises(IngestError):
            write_export(corrupted, target)
        self.assertFalse(target.exists())

    def test_cli_export_and_report_reruns(self):
        source, manifest = self.source()
        target, report = self.directory / "output.jsonl", self.directory / "report.json"
        first = self.cli(source, manifest, "--output", target, "--report", report)
        self.assertEqual(first.returncode, 0, first.stderr)
        initial = target.read_bytes()
        initial_report = report.read_bytes()
        second = self.cli(source, manifest, "--output", target, "--report", report)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(initial, target.read_bytes())
        self.assertEqual(initial_report, report.read_bytes())
        self.assertEqual(json.loads(second.stdout)["export_status"], "WRITTEN")

    def test_cli_dry_run_reports_failure_and_writes_no_export(self):
        self.rows[2]["parent_id"] = "missing"
        source, manifest = self.source()
        report = self.directory / "report.json"
        process = self.cli(source, manifest, "--dry-run", "--report", report)
        self.assertEqual(process.returncode, 1)
        audit = json.loads(report.read_bytes())
        self.assertFalse(audit["valid"])
        self.assertEqual(audit["export_status"], "NOT_WRITTEN")
        self.assertFalse((self.directory / "output.jsonl").exists())

    def test_cli_rejected_input_preserves_existing_export(self):
        source, manifest = self.source(self.rows[:-1])
        target = self.directory / "output.jsonl"
        target.write_bytes(b"previous reviewed artifact\n")
        process = self.cli(source, manifest, "--output", target)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(target.read_bytes(), b"previous reviewed artifact\n")

    def test_cli_refuses_input_overwrite_and_colliding_reports(self):
        source, manifest = self.source()
        initial = source.read_bytes()
        for arguments in (("--output", source), ("--dry-run", "--report", source),
                          ("--output", self.directory / "same", "--report", self.directory / "same")):
            with self.subTest(arguments=arguments):
                process = self.cli(source, manifest, *arguments)
                self.assertEqual(process.returncode, 1)
                self.assertEqual(json.loads(process.stdout)["code"], "UNSAFE_OUTPUT_PATH")
                self.assertEqual(source.read_bytes(), initial)

    def test_cli_refuses_manifest_overwrite(self):
        source, manifest = self.source()
        target = self.directory / "manifest.json"
        process = self.cli(source, manifest, "--output", target)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(load_manifest(target), manifest)

    def test_cli_refuses_input_hardlink_alias(self):
        source, manifest = self.source()
        target = self.directory / "alias.jsonl"
        try:
            os.link(source, target)
        except OSError as exc:
            self.skipTest(f"hardlinks unavailable: {exc}")
        process = self.cli(source, manifest, "--output", target)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["code"], "UNSAFE_OUTPUT_PATH")

    def test_cli_requires_output_and_disallows_output_in_dry_run(self):
        source, manifest = self.source()
        self.assertEqual(self.cli(source, manifest).returncode, 2)
        self.assertEqual(self.cli(source, manifest, "--dry-run", "--output",
                                  self.directory / "out.jsonl").returncode, 2)

    def test_unpaired_surrogate_title_is_rejected(self):
        self.rows[2]["title"] = "bad\ud800"
        # Escaped JSON can represent a surrogate but cannot produce valid UTF-8 title text.
        source, manifest = self.source(raw=json.dumps(self.rows, ensure_ascii=True).encode())
        result = ingest(source, manifest, profile="synthetic", strict=False)
        self.assertIn("INVALID_RECORD", {i["code"] for i in result.report["issues"]})


if __name__ == "__main__":
    unittest.main()
