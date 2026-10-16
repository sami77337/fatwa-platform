"""Whole synthetic batches remain accountable across exact intake boundaries."""
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import apps.prepared_pipeline as pipeline
from apps.fatwa_drafts.intake import ReferenceLink, ValidationError, parse_intake, serialize_intake
from apps.reference_links.resolution import Heading, SnapshotCatalog
from tools.content_intake.cli import SCHEMA, artifacts, normalize


def raw_rows(rows):
    return json.dumps({"schema": SCHEMA, "items": rows}, ensure_ascii=False).encode("utf-8")


def row(external_id="SYN-E1-valid", **changes):
    return {"external_id": external_id, "question": " \tسُؤالٌ اصطناعيّ\r\nالسطرُ الثاني\n  ",
            "prepared_clip_url": "https://example.invalid/finished.mp4", **changes}


class Wave6ContractTests(unittest.TestCase):
    def test_published_synthetic_example(self):
        example = Path(__file__).resolve().parents[2] / "docs/dev/e1/synthetic_example.py"
        raw, mapping, bridge, catalog = runpy.run_path(str(example))["build_inputs"]()
        batch = pipeline.prepare_batch(raw, synthetic_fixtures_only=True, reference_map=mapping, catalog=catalog)
        self.assertEqual(len(batch.report["items"]), 7)
        self.assertEqual(len(batch.drafts), 3)
        self.assertEqual(batch.report["summary"], {"ready-for-editor": 2, "blocked-invalid": 3,
                                                  "needs-editor-review": 2, "references-unverified": 6})
        self.assertEqual(batch.drafts[0].intake.staff_notes, " ملاحظةٌ\t\n ")
        self.assertEqual(batch.drafts[0].intake.question, " \tسُؤالٌ اصطناعيّ\r\nالسطرُ الثاني\n  ")
        self.assertEqual(batch.drafts[0].intake.reference_links[0].source_id, bridge.headings[0].c2_source_id)
        reports = batch.report["items"]
        self.assertEqual(reports[0]["references"][0]["outcome"], "verified")
        self.assertEqual(reports[5]["references"][0]["outcome"], "unverified")
        self.assertEqual(reports[6]["references"][0]["outcome"], "mismatched")

    def test_mixed_batch_keeps_every_row_without_fabricated_drafts(self):
        pointers = [{"source_id": "synthetic-source", "heading_id": "opaque-heading"},
                    {"source_id": "mismatched-source", "heading_id": "opaque-other"}]
        identity = ReferenceLink("synthetic-only", "fake-book", "fake-edition", "a" * 64, "b" * 64, "opaque")
        mapping = {pipeline.C1Pointer(**pointer): pipeline.ExplicitMapping(identity, 7, 9 + i, "synthetic-test")
                   for i, pointer in enumerate(pointers)}
        catalog = SnapshotCatalog([
            Heading(7, 9 + i, "مرجع اصطناعي", "باب اصطناعي", "الأول", 12,
                    ("باب اصطناعي",), namespace, "fake-book", "b" * 64)
            for i, namespace in enumerate(("synthetic-only", "different-namespace"))
        ])
        rows = [row(reference_links=[pointers[0]]), row("SYN-E1-missing", prepared_clip_url=""),
                row("SYN-E1-invalid", prepared_clip_url="https://example.invalid:444/a"),
                row("SYN-E1-duplicate"), row("SYN-E1-duplicate"),
                row("SYN-E1-unmapped", reference_links=[{"source_id": "unknown", "heading_id": "unknown"}]),
                row("SYN-E1-mismatch", reference_links=[pointers[1]])]
        before = json.loads(raw_rows(rows))
        batch = pipeline.prepare_batch(raw_rows(rows), synthetic_fixtures_only=True,
                                       reference_map=mapping, catalog=catalog)
        reports = batch.report["items"]
        self.assertEqual([report["original"] for report in reports], before["items"])
        self.assertEqual(batch.report["summary"], {"ready-for-editor": 2, "blocked-invalid": 3,
                                                  "needs-editor-review": 2, "references-unverified": 6})
        self.assertEqual([draft.intake.external_id for draft in batch.drafts],
                         ["SYN-E1-valid", "SYN-E1-unmapped", "SYN-E1-mismatch"])
        self.assertEqual(reports[0]["references"][0]["outcome"], "verified")
        self.assertIsNone(reports[1]["draft"])
        self.assertEqual(reports[1]["original"]["prepared_clip_url"], "")
        self.assertEqual(reports[5]["references"][0]["outcome"], "unverified")
        self.assertEqual(reports[6]["references"][0]["outcome"], "mismatched")
        for report in reports[2:5]:
            self.assertIn("blocked-invalid", report["statuses"])
            self.assertIsNone(report["draft"])
        for draft in batch.drafts:
            self.assertEqual(draft.intake.question, rows[0]["question"])
            self.assertEqual(parse_intake(serialize_intake((draft.intake,))), (draft.intake,))
            self.assertEqual((draft.current.action, draft.current.answer), ("received", ""))
        self.assertEqual(json.loads(batch.json_bytes())["items"][1]["original"], rows[1])

    def test_over_limit_references_block_before_c1_normalization(self):
        oversized = row(reference_links=[{"source_id": str(i), "heading_id": "h"} for i in range(101)])
        with patch.object(pipeline, "normalize", wraps=normalize) as calls:
            batch = pipeline.prepare_batch(raw_rows([oversized, row("synthetic-next")]),
                                           synthetic_fixtures_only=True)
        self.assertEqual(len(batch.report["items"]), 2)
        self.assertEqual(len(batch.drafts), 1)
        self.assertIn("blocked-invalid", batch.report["items"][0]["statuses"])
        self.assertTrue(all(len(call.args[0][0].get("reference_links", [])) <= 100
                            for call in calls.call_args_list))

    def test_c1_media_eligibility_does_not_weaken_c2_https_port(self):
        for url, eligible in (("http://example.invalid/a", False),
                              ("https://example.invalid:8443/a", False),
                              ("https://example.invalid:443/a", True),
                              ("https://example.invalid/a", True)):
            with self.subTest(url=url):
                raw = raw_rows([row(prepared_clip_url=url)])
                outputs, manifest = artifacts(raw, ".json")
                self.assertEqual(manifest["status"], "VALID")
                batch = pipeline.prepare_batch(outputs["intake.json"], synthetic_fixtures_only=True)
                self.assertEqual(bool(batch.drafts), eligible)
                self.assertEqual(batch.report["items"][0]["original"]["prepared_clip_url"], url)
                if not eligible:
                    self.assertIn("blocked-invalid", batch.report["items"][0]["statuses"])

    def test_original_url_is_never_trimmed_into_an_eligible_draft(self):
        url = " https://example.invalid/finished.mp4 "
        outputs, manifest = artifacts(raw_rows([row(prepared_clip_url=url)]), ".json")
        self.assertEqual(manifest["status"], "INVALID")
        self.assertEqual(json.loads(outputs["intake.json"])["items"], [])
        batch = pipeline.prepare_batch(raw_rows([row(prepared_clip_url=url)]), synthetic_fixtures_only=True)
        self.assertEqual(batch.drafts, ())
        self.assertEqual(batch.report["items"][0]["original"]["prepared_clip_url"], url)

    def test_bad_envelopes_and_nested_keys_reject_the_whole_call(self):
        for raw in (b'[]', b'{"schema":"fatwa.prepared-intake.v1","items":[]}',
                    raw_rows([row()]).replace(b'"items":', b'"reference_map":{},"items":'),
                    raw_rows([row()]).replace(b'"external_id":', b'"external_id":"duplicate","external_id":'),
                    b'{"schema":"fatwa.prepared-intake.v1","items":[{"unknown":"\\ud800"}]}'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                pipeline.prepare_batch(raw, synthetic_fixtures_only=True)

    def test_numeric_overflow_cannot_make_an_unserializable_report(self):
        raw = b'{"schema":"fatwa.prepared-intake.v1","items":[{"unknown":1e999}]}'
        with self.assertRaises(ValidationError):
            pipeline.prepare_batch(raw, synthetic_fixtures_only=True)

    def test_typed_map_is_only_a_trusted_caller_argument(self):
        for field in ("reference_map", "bridge_config", "catalog", "edition_id"):
            batch = pipeline.prepare_batch(raw_rows([row(**{field: {}})]), synthetic_fixtures_only=True)
            self.assertEqual(batch.drafts, ())
            self.assertEqual(batch.report["items"][0]["original"][field], {})
            self.assertIn("blocked-invalid", batch.report["items"][0]["statuses"])
        with self.assertRaises(ValidationError):
            pipeline.prepare_batch(raw_rows([row()]), synthetic_fixtures_only=True,
                                   reference_map={"payload-derived": {"edition_id": 7}})
