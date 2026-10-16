"""Synthetic regressions for exact C1 bytes-to-text handling and bounded intake."""
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.fatwa_drafts.intake import parse_intake, serialize_intake
from apps.prepared_pipeline import prepare_batch
from tools.content_intake.cli import SCHEMA, artifacts, main, normalize


QUESTION = "  \tسُؤالٌ اصطناعيّ فقط؟\r\nالسطرُ الثاني\n\t  "
NOTES = " \tملاحظاتٌ تجريبيّة\r\n  "


def synthetic_row(**changes):
    return {"external_id": "SYN-E1-exact", "question": QUESTION,
            "prepared_clip_url": "https://example.invalid/finished.mp4",
            "staff_notes": NOTES, "reference_links": [], **changes}


def adapter_bytes(row, suffix):
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow({**row, "reference_links": json.dumps(row.get("reference_links", []))})
        return stream.getvalue().encode("utf-8")
    return (json.dumps([row] if suffix == ".json" else row, ensure_ascii=False)
            + "\n").encode("utf-8")


class ExactPreparedTests(unittest.TestCase):
    def test_original_strings_reach_d1_and_c2_from_every_adapter(self):
        for suffix in (".json", ".jsonl", ".csv"):
            with self.subTest(suffix=suffix):
                row = synthetic_row()
                outputs, manifest = artifacts(adapter_bytes(row, suffix), suffix)
                self.assertEqual(manifest["status"], "VALID")
                self.assertEqual(json.loads(outputs["intake.json"])["items"], [row])
                self.assertEqual(json.loads(outputs["intake.jsonl"]), row)
                # The second adapter roundtrip must not silently normalize the first.
                self.assertEqual(artifacts(outputs["intake.jsonl"], ".jsonl")[0], outputs)
                batch = prepare_batch(outputs["intake.json"], synthetic_fixtures_only=True)
                intake = batch.drafts[0].intake
                self.assertEqual((intake.question, intake.staff_notes), (QUESTION, NOTES))
                self.assertEqual(parse_intake(serialize_intake((intake,))), (intake,))
                self.assertEqual(json.loads(batch.json_bytes())["items"][0]["original"], row)

    def test_title_fallback_preserves_original_text(self):
        row = synthetic_row(title=QUESTION)
        del row["question"]
        for suffix in (".json", ".jsonl", ".csv"):
            with self.subTest(suffix=suffix):
                outputs, manifest = artifacts(adapter_bytes(row, suffix), suffix)
                self.assertEqual(manifest["status"], "VALID")
                self.assertEqual(json.loads(outputs["intake.json"])["items"][0]["question"], QUESTION)
                batch = prepare_batch(outputs["intake.json"], synthetic_fixtures_only=True)
                self.assertEqual(batch.drafts[0].intake.question, QUESTION)

    def test_formula_review_preserves_spaces_and_newlines(self):
        row = synthetic_row(staff_notes=" \t=synthetic_formula\n ")
        outputs, manifest = artifacts(adapter_bytes(row, ".csv"), ".csv")
        self.assertEqual(manifest["status"], "REVIEW_REQUIRED")
        self.assertEqual(json.loads(outputs["intake.json"])["items"][0]["staff_notes"], row["staff_notes"])

    def test_jsonl_unicode_separators_are_question_text_not_record_delimiters(self):
        row = synthetic_row(question="سطرٌ\u2028وسطرٌ\u2029وآخر\u0085اصطناعي")
        outputs, manifest = artifacts(adapter_bytes(row, ".jsonl"), ".jsonl")
        self.assertEqual(manifest["status"], "VALID")
        self.assertEqual(json.loads(outputs["intake.jsonl"]), row)

    def test_blank_required_text_still_invalid(self):
        items, findings = normalize([synthetic_row(question=" \r\n\t ")])
        self.assertEqual(items, [])
        self.assertIn("required", [f["code"] for f in findings])

    def test_input_byte_limit_for_every_adapter(self):
        for suffix in (".json", ".jsonl", ".csv"):
            prefix = adapter_bytes(synthetic_row(), suffix)
            padding = b" " if suffix == ".json" else b"\n"
            raw = prefix + padding * (1_000_001 - len(prefix))
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                artifacts(raw, suffix)

    def test_row_limit_for_every_adapter(self):
        row = synthetic_row(question="synthetic", staff_notes="")
        for suffix in (".json", ".jsonl", ".csv"):
            if suffix == ".json":
                raw = json.dumps([row] * 1001).encode()
            elif suffix == ".jsonl":
                raw = (json.dumps(row) + "\n").encode() * 1001
            else:
                lines = adapter_bytes(row, suffix).splitlines(keepends=True)
                raw = lines[0] + lines[1] * 1001
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                artifacts(raw, suffix)

    def test_exact_byte_row_and_reference_maxima_are_accepted(self):
        rows = [synthetic_row(external_id=f"SYN-{index}") for index in range(1000)]
        rows[0]["reference_links"] = [{"source_id": str(i), "heading_id": "h"} for i in range(100)]
        raw = json.dumps({"schema": SCHEMA, "items": rows}).encode()
        raw += b" " * (1_000_000 - len(raw))
        outputs, manifest = artifacts(raw, ".json")
        self.assertEqual((len(raw), manifest["status"], manifest["valid_row_count"]), (1_000_000, "VALID", 1000))
        self.assertEqual(len(json.loads(outputs["intake.json"])["items"][0]["reference_links"]), 100)
        batch = prepare_batch(raw, synthetic_fixtures_only=True)
        self.assertEqual((len(batch.report["items"]), len(batch.drafts)), (1000, 1000))

    def test_normalize_stops_bounded_row_iterator(self):
        def rows():
            for index in range(1001):
                yield synthetic_row(external_id=f"synthetic-{index}")
            self.fail("consumed more than the row limit plus one sentinel")
        with self.assertRaises(ValueError):
            normalize(rows())

    def test_reference_limit_before_scanning_values(self):
        class UnreadableReferences(list):
            def __iter__(self):
                raise AssertionError("over-limit references were traversed")
        row = synthetic_row(reference_links=UnreadableReferences([{}] * 101))
        items, findings = normalize([row])
        self.assertEqual(items, [])
        self.assertIn("expected_list_at_most_100", [f["code"] for f in findings])

    def test_encoded_csv_reference_limit(self):
        row = synthetic_row(reference_links=[{"source_id": str(i), "heading_id": "x"} for i in range(101)])
        outputs, manifest = artifacts(adapter_bytes(row, ".csv"), ".csv")
        self.assertEqual(manifest["status"], "INVALID")
        self.assertEqual(json.loads(outputs["intake.json"])["items"], [])

    def test_invalid_unicode_in_rejected_rows_is_rejected_before_serialization(self):
        for value in ([{"external_id": "synthetic", "unknown": "\ud800"}], ["\udfff"]):
            for suffix in (".json", ".jsonl"):
                raw = json.dumps(value if suffix == ".json" else value[0]).encode()
                with self.subTest(value=ascii(value), suffix=suffix), self.assertRaises(ValueError):
                    artifacts(raw, suffix)

    def test_nested_duplicate_json_keys_rejected_in_all_adapters(self):
        link = '{"source_id":"s","source_id":"other","heading_id":"h"}'
        for suffix in (".json", ".jsonl"):
            raw = ('{"external_id":"s","question":"q","reference_links":[' + link + "]}")
            raw = ("[" + raw + "]" if suffix == ".json" else raw).encode()
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                artifacts(raw, suffix)
        row = synthetic_row()
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow({**row, "reference_links": "[" + link + "]"})
        _, manifest = artifacts(stream.getvalue().encode(), ".csv")
        self.assertEqual(manifest["status"], "INVALID")

    def test_json_numeric_overflow_is_rejected_even_in_unknown_fields(self):
        raw = b'{"external_id":"synthetic","question":"q","unknown":1e999}'
        for suffix in (".json", ".jsonl"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                artifacts(b"[" + raw + b"]" if suffix == ".json" else raw, suffix)

    def test_untrusted_mapping_fields_cannot_become_canonical(self):
        for field in ("reference_map", "catalog", "bridge_config", "edition_id"):
            outputs, manifest = artifacts(adapter_bytes(synthetic_row(**{field: {}}), ".json"), ".json")
            self.assertEqual(manifest["status"], "INVALID")
            self.assertEqual(json.loads(outputs["intake.json"])["items"], [])

    def test_oversized_cli_input_returns_invalid_without_export(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=root / "tests/content_intake") as directory:
            source = Path(directory) / "synthetic.json"
            source.write_bytes(b" " * 1_000_001)
            bundle = Path(directory) / "bundle"
            result = subprocess.run([sys.executable, "-m", "tools.content_intake", "export",
                                     str(source), "--bundle", str(bundle)], cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
            self.assertFalse(bundle.exists())

    def test_cli_reads_at_most_the_byte_limit_plus_one(self):
        class BoundedRead(io.BytesIO):
            def read(self, size=-1):
                self_test.assertTrue(0 <= size <= 1_000_001, "unbounded input read")
                return super().read(size)
        self_test = self
        stdout = io.BytesIO()
        with patch.object(Path, "open", return_value=BoundedRead(b" " * 1_000_002)), \
             patch("sys.stdout", SimpleNamespace(buffer=stdout)):
            result = main(["validate", "synthetic.json"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "INVALID")
