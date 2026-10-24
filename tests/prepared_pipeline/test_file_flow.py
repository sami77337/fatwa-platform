"""Direct preparation retains rejected input and exposes actionable workbench results."""

import csv
import hashlib
import io
import json
import unittest

import apps.prepared_pipeline as pipeline
from apps.fatwa_drafts.intake import ReferenceLink, ValidationError
from apps.reference_links.resolution import Heading, SnapshotCatalog
from tools.content_intake.cli import SCHEMA


def row(identity="SYN-unseen-أ", **changes):
    return (
        dict(
            external_id=identity,
            question=" \tسُؤَالٌ\u200f\r\nثانٍ\u2028أخير  ",
            prepared_clip_url="https://example.invalid/prepared.mp4",
            staff_notes=" ملاحظةٌ\r\n\t ",
            reference_links=[],
        )
        | changes
    )


def file_bytes(rows, suffix):
    if suffix == ".json":
        return json.dumps(dict(schema=SCHEMA, items=rows), ensure_ascii=False).encode("utf-8")
    if suffix == ".jsonl":
        return (
            "\r\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\r\n"
        ).encode()
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    for item in rows:
        writer.writerow(
            {**item, "reference_links": json.dumps(item["reference_links"], ensure_ascii=False)}
        )
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


class FileFlowTests(unittest.TestCase):
    def test_reference_reasons_and_arabic_preview_use_original_pointer_positions(self):
        pointers = [
            {"source_id": "s" * 101, "heading_id": "invalid"},
            {"source_id": "s", "heading_id": "unmapped"},
        ]
        batch = pipeline.prepare_batch(
            file_bytes([row(reference_links=pointers)], ".json"), synthetic_fixtures_only=True
        )
        findings = batch.report["items"][0]["findings"]
        self.assertEqual(
            [(f["code"], f["reference_index"]) for f in findings],
            [("invalid_pointer", 1), ("needs_mapping", 2)],
        )
        reasons = batch.workbench_summary()["rows"][0]["reference_reasons"]
        self.assertEqual(
            reasons,
            [
                {
                    "reference_index": 2,
                    "outcome": "unverified",
                    "reasons": ["unsupported_C1_identity_needs_mapping"],
                }
            ],
        )
        self.assertIn("الإحالة 2: unverified", batch.preview_ar())

    def test_csv_cell_errors_keep_named_findings_and_overflow_values_in_json_report(self):
        raw = (
            "external_id,question,prepared_clip_url,staff_notes,reference_links\r\n"
            "SYN-short,سؤال اصطناعي\r\n"
            "SYN-long,سؤال اصطناعي,https://example.invalid/a,,[],إضافيّ\r\n"
        ).encode()
        batch = pipeline.prepare_file(raw, ".csv", synthetic_fixtures_only=True)
        report = json.loads(batch.json_bytes())
        missing = {
            f["field"] for f in report["items"][0]["findings"] if f["code"] == "csv_missing_cell"
        }
        self.assertEqual(missing, {"prepared_clip_url", "staff_notes", "reference_links"})
        self.assertEqual(report["items"][1]["csv_extra_cells"], ["إضافيّ"])
        self.assertEqual(report["workbench"]["status_counts"]["blocked-invalid"], 2)

    def test_formats_prepare_unseen_ids_and_keep_exact_arabic_and_rejected_rows(self):
        originals = [row(), row("SYN-bad", prepared_clip_url="file:///synthetic.mp4")]
        for suffix in (".json", ".jsonl", ".csv"):
            with self.subTest(suffix=suffix):
                raw = file_bytes(originals, suffix)
                batch = pipeline.prepare_file(raw, suffix, synthetic_fixtures_only=True)
                self.assertEqual(
                    [draft.intake.external_id for draft in batch.drafts], ["SYN-unseen-أ"]
                )
                self.assertEqual(batch.drafts[0].intake.question, originals[0]["question"])
                self.assertEqual(batch.drafts[0].intake.staff_notes, originals[0]["staff_notes"])
                self.assertEqual(batch.report["input_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(batch.report["input_format"], suffix)
                self.assertEqual(len(batch.report["items"]), 2)
                self.assertEqual(
                    batch.report["items"][1]["original"]["prepared_clip_url"],
                    "file:///synthetic.mp4",
                )
                self.assertIn("blocked-invalid", batch.report["items"][1]["statuses"])
                self.assertEqual(
                    batch.json_bytes(),
                    pipeline.prepare_file(raw, suffix, synthetic_fixtures_only=True).json_bytes(),
                )

    def test_csv_reference_cell_resolves_only_through_explicit_trusted_mapping(self):
        pointer = dict(source_id="مصدر-اصطناعي", heading_id="opaque-٩")
        raw = file_bytes([row(reference_links=[pointer])], ".csv")
        link = ReferenceLink("synthetic", "book", "edition", "a" * 64, "b" * 64, "opaque-c2")
        mappings = {
            pipeline.C1Pointer(**pointer): pipeline.ExplicitMapping(
                link, 7, 9, "synthetic-file-test"
            )
        }
        catalog = SnapshotCatalog(
            [
                Heading(
                    7, 9, "مرجع اصطناعي", "عنوانٌ", "١", 2, ("عنوانٌ",), "synthetic", "book", "b" * 64
                )
            ]
        )
        batch = pipeline.prepare_file(
            raw, ".csv", synthetic_fixtures_only=True, reference_map=mappings, catalog=catalog
        )
        self.assertEqual(batch.drafts[0].intake.reference_links, (link,))
        self.assertEqual(batch.report["items"][0]["references"][0]["outcome"], "verified")
        self.assertIsInstance(batch.report["items"][0]["original"]["reference_links"], str)

    def test_bad_reference_list_does_not_hide_other_field_failures(self):
        source = row(
            external_id=" bad ",
            question="",
            prepared_clip_url="http://example.invalid/a",
            reference_links=[dict(source_id="s", heading_id="h")] * 101,
        )
        batch = pipeline.prepare_batch(file_bytes([source], ".json"), synthetic_fixtures_only=True)
        errors = {
            finding["field"]
            for finding in batch.report["items"][0]["findings"]
            if finding["severity"] == "error"
        }
        self.assertTrue(
            {"external_id", "question", "prepared_clip_url", "reference_links"} <= errors, errors
        )
        self.assertEqual(batch.report["items"][0]["original"], source)

    def test_missing_clip_does_not_hide_c2_errors(self):
        batch = pipeline.prepare_batch(
            file_bytes([row(prepared_clip_url="", staff_notes="x" * 20001)], ".json"),
            synthetic_fixtures_only=True,
        )
        self.assertIn("blocked-invalid", batch.report["items"][0]["statuses"])
        self.assertTrue(
            any(f["field"] == "staff_notes" for f in batch.report["items"][0]["findings"])
        )

    def test_workbench_summary_accounts_for_rejections_receipts_and_review_separately(self):
        rows = [row(), row("SYN-missing", prepared_clip_url=""), row("SYN-bad", question="")]
        batch = pipeline.prepare_batch(file_bytes(rows, ".json"), synthetic_fixtures_only=True)
        summary = batch.workbench_summary()
        self.assertEqual((summary["record_count"], summary["draft_count"]), (3, 1))
        self.assertEqual(
            summary["status_counts"],
            {
                "ready-for-editor": 1,
                "needs-editor-review": 1,
                "blocked-invalid": 1,
                "references-unverified": 3,
            },
        )
        self.assertEqual(summary["rows"][2]["external_id"], "SYN-bad")
        self.assertEqual(
            summary["rows"][2]["rejection_reasons"], [{"field": "question", "code": "required"}]
        )
        self.assertEqual(
            summary["rows"][1]["review_reasons"],
            [{"field": "prepared_clip_url", "code": "media_link_missing_review_required"}],
        )
        self.assertEqual(
            summary["finding_counts"], {"media_link_missing_review_required": 1, "required": 1}
        )
        self.assertEqual(summary["reference_counts"], {})
        self.assertEqual(json.loads(batch.json_bytes())["workbench"], summary)

    def test_reference_findings_have_per_pointer_locations_and_preserve_aliases(self):
        pointers = [
            dict(source_id="synthetic", heading_id="a"),
            dict(source_id="synthetic", heading_id="b"),
        ]
        link = ReferenceLink("synthetic", "book", "edition", "a" * 64, "b" * 64, "same")
        mapping = {
            pipeline.C1Pointer(**p): pipeline.ExplicitMapping(link, 7, 9, "synthetic-alias-test")
            for p in pointers
        }
        batch = pipeline.prepare_batch(
            file_bytes([row(reference_links=pointers)], ".json"),
            synthetic_fixtures_only=True,
            reference_map=mapping,
        )
        self.assertEqual(len(batch.report["items"][0]["references"]), 2)
        self.assertTrue(
            any(
                f["field"] == "reference_links"
                and f["code"] == "duplicate_mapped_reference"
                and f["reference_index"] == 2
                for f in batch.report["items"][0]["findings"]
            )
        )
        self.assertEqual(batch.drafts, ())

    def test_file_boundary_guard_and_safe_malformed_input(self):
        raw = file_bytes([row()], ".json")
        with self.assertRaises(ValidationError):
            pipeline.prepare_file(raw, ".json")
        for malformed, suffix in (
            (b"[]", ".json"),
            (raw, ".txt"),
            (b"\xff", ".csv"),
            (b'{"private-looking-key":1,"private-looking-key":2}', ".json"),
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValidationError) as caught:
                pipeline.prepare_file(malformed, suffix, synthetic_fixtures_only=True)
            self.assertNotIn("private-looking-key", str(caught.exception))
