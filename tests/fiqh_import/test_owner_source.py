"""Acceptance against the owner ZIP if present; never copy raw source into git."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from tools.fiqh_import import ingest, load_manifest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "_codex_input" / "FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip"
ARCHIVE_PIN = "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce"
PREFIX = "FATWA_622_FIQH_COMPLETE/"


@unittest.skipUnless(ARCHIVE.is_file(), "SOURCE_DATA_MISSING: owner ZIP was not supplied")
class OwnerSourceAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_PIN:
            raise AssertionError("owner ZIP SHA256 differs from the owner pin")
        with zipfile.ZipFile(ARCHIVE) as archive:
            names = archive.namelist()
            original_name = next(n for n in names if n.endswith("622_العناوين_الأصلية_ID_title.csv"))
            raw = archive.read(original_name).decode("utf-8-sig")
            originals = list(csv.DictReader(io.StringIO(raw, newline="")))
            cls.originals = {row["title_id"]: row["original_title"] for row in originals}
            if len(originals) != 11397 or len(cls.originals) != 11397:
                raise AssertionError("original title index is incomplete or has duplicate IDs")
            cls.members = {
                "csv": next(n for n in names if n.endswith("11397.csv")),
                "jsonl": next(n for n in names if n.endswith("11397.jsonl")),
                "json": next(n for n in names if n.endswith("متداخلة.json")),
            }
            cls.raw_members = {kind: archive.read(name) for kind, name in cls.members.items()}

    def accept(self, file_format):
        raw = self.raw_members[file_format]
        scratch = Path(__file__).parent / ".scratch"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / ("owner-source." + file_format)
            path.write_bytes(raw)
            manifest = load_manifest(ROOT / "docs/data-ingest/owner-622-r1-jsonl.manifest.json")
            manifest = replace(manifest, dataset_id="owner-622-r1-" + file_format,
                               input_sha256=hashlib.sha256(raw).hexdigest(),
                               provenance="Owner archive SHA256 " + ARCHIVE_PIN +
                               "; member " + self.members[file_format] +
                               "; direct original Lucene title labels from the supplied edition")
            first = ingest(path, manifest, profile="real-622", input_adapter="owner-622-r1")
            second = ingest(path, manifest, profile="real-622", input_adapter="owner-622-r1")
            self.assertEqual(first.output_bytes, second.output_bytes)
            self.assertEqual(first.report, second.report)
            self.assertEqual(first.report["unique_valid_records"], 11397)
            self.assertEqual(first.report["reachable_nodes"], 11397)
            self.assertEqual(first.report["roots"], 32)
            self.assertEqual(first.report["max_depth"], 5)
            self.assertEqual(first.report["direct_titles"], 11397)
            self.assertEqual(first.report["inferred_titles"], 0)
            self.assertEqual(first.report["issues"], [])
            self.assertEqual(first.report["real_source_acceptance"], "STRUCTURE_VALIDATED")
            self.assertEqual(hashlib.sha256(first.output_bytes).hexdigest(), first.report["output_sha256"])
            output = [json.loads(line) for line in first.output_bytes.split(b"\n") if line]
            self.assertEqual({row["source_id"]: row["title"] for row in output}, self.originals)
            self.assertEqual(sum(row["root_kind"] == "fiqh_book" for row in output), 30)
            self.assertEqual(sum(row["root_kind"] == "introduction" for row in output), 2)
            print(json.dumps({
                "acceptance_fixture": self.members[file_format],
                "archive_sha256": ARCHIVE_PIN,
                "input_sha256": first.report["input_sha256"],
                "output_sha256": first.report["output_sha256"],
                "nodes": 11397, "exact_original_id_title_matches": 11397,
                "deployment_status": "NOT_DEPLOYED",
            }, ensure_ascii=True, sort_keys=True))

    def test_owner_jsonl_exact_titles_structure_and_rerun_bytes(self):
        self.accept("jsonl")

    def test_owner_csv_exact_titles_structure_and_rerun_bytes(self):
        self.accept("csv")

    def test_owner_nested_json_exact_titles_structure_and_rerun_bytes(self):
        self.accept("json")


if __name__ == "__main__":
    unittest.main()
