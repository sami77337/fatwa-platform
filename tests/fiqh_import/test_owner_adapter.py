"""Synthetic examples of the observed owner format; no original headings copied."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tools.fiqh_import import IngestError, Manifest, ingest
from tools.fiqh_import.owner_r1 import flatten_tree


class OwnerAdapterTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).parent / ".scratch"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.rows = [
            {"id": 1, "parent_id": None, "title": "Synthetic introduction",
             "depth": 1, "position_among_siblings": 1, "children_count": 1,
             "is_leaf": False, "source_page_id": 2, "source_part": "المقدمة",
             "source_page_number": 5, "source_entry_number": None,
             "path_ids": [1], "path_titles": ["Synthetic introduction"], "lucene_title_key": "622-1"},
            {"id": 2, "parent_id": 1, "title": "Synthetic child",
             "depth": 2, "position_among_siblings": 1, "children_count": 0,
             "is_leaf": True, "source_page_id": 2, "source_part": "المقدمة",
             "source_page_number": 5, "source_entry_number": None,
             "path_ids": [1, 2], "path_titles": ["Synthetic introduction", "Synthetic child"],
             "lucene_title_key": "622-2"},
        ]

    def source(self, file_format="jsonl", value=None):
        value = self.rows if value is None else value
        if file_format == "jsonl":
            raw = ("\n".join(json.dumps(row, ensure_ascii=False) for row in value) + "\n").encode("utf-8")
        elif file_format == "json":
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        else:
            text = io.StringIO(newline="")
            writer = csv.DictWriter(text, fieldnames=list(value[0]))
            writer.writeheader()
            for row in value:
                row = dict(row)
                # The actual CSV has string path fields rather than JSON arrays.
                row["path_ids"] = " > ".join(map(str, row["path_ids"]))
                row["path_titles"] = " ← ".join(row["path_titles"])
                writer.writerow(row)
            raw = text.getvalue().encode("utf-8")
        path = self.directory / ("source." + file_format)
        path.write_bytes(raw)
        manifest = Manifest(
            dataset_id="synthetic-owner-format", source_kind="synthetic", book_id="622",
            edition="Synthetic edition", provenance="Synthetic test of the owner adapter",
            input_sha256=hashlib.sha256(raw).hexdigest(),
            expected_nodes=2, expected_roots=1, expected_max_depth=2,
        )
        return path, manifest

    def tree(self):
        child = {key: self.rows[1][key] for key in (
            "id", "parent_id", "title", "depth", "source_page_id", "source_part", "source_page_number")}
        child.update(order=1, children=[])
        root = {key: self.rows[0][key] for key in (
            "id", "parent_id", "title", "depth", "source_page_id", "source_part", "source_page_number")}
        root.update(order=1, children=[child])
        return {"source": {"work_id": 622}, "scope": "CONTENTS_TREE_ONLY_NOT_FULL_TEXT",
                "total_nodes": 2, "root_count": 1, "roots": [root]}

    def diagnostic(self):
        path, manifest = self.source()
        return ingest(path, manifest, profile="synthetic", input_adapter="owner-622-r1", strict=False)

    def test_flat_jsonl_and_csv_keep_named_part_and_original_ids(self):
        for file_format in ("jsonl", "csv"):
            with self.subTest(file_format=file_format):
                path, manifest = self.source(file_format)
                result = ingest(path, manifest, profile="synthetic", input_adapter="owner-622-r1")
                rows = [json.loads(line) for line in result.output_bytes.split(b"\n") if line]
                self.assertEqual(rows[0]["part"], "المقدمة")
                self.assertEqual(rows[0]["source_part"], "المقدمة")
                self.assertEqual(rows[0]["source_id"], "1")
                self.assertEqual(rows[0]["root_kind"], "introduction")
                expected_id = 1 if file_format == "jsonl" else "1"
                self.assertEqual(rows[0]["source_metadata"]["id"], expected_id)
                self.assertEqual(rows[0]["source_metadata"]["lucene_title_key"], "622-1")
                self.assertEqual(result.report["direct_titles"], 2)
                self.assertEqual(result.report["inferred_titles"], 0)

    def test_nested_json_adapter_preserves_tree_order_and_titles(self):
        path, manifest = self.source("json", self.tree())
        result = ingest(path, manifest, profile="synthetic", input_adapter="owner-622-r1")
        rows = [json.loads(line) for line in result.output_bytes.split(b"\n") if line]
        self.assertEqual([row["title"] for row in rows], [row["title"] for row in self.rows])
        self.assertEqual(rows[1]["parent_id"], "1")
        self.assertEqual(rows[1]["source_metadata"]["order"], 1)

    def test_named_part_does_not_allow_blank_or_arbitrary_missing_reference(self):
        for part in ("", None, "unknown volume", "0"):
            with self.subTest(part=part):
                self.rows[0]["source_part"] = part
                self.assertFalse(self.diagnostic().report["valid"])

    def test_title_key_must_match_book_and_id(self):
        self.rows[1]["lucene_title_key"] = "21642-2"
        self.assertFalse(self.diagnostic().report["valid"])

    def test_declared_depth_must_match_edges(self):
        self.rows[1]["depth"] = 3
        result = self.diagnostic()
        self.assertIn("SOURCE_DEPTH_MISMATCH", {i["code"] for i in result.report["issues"]})

    def test_declared_child_count_and_leaf_must_match_edges(self):
        self.rows[0]["children_count"] = 0
        self.rows[0]["is_leaf"] = True
        result = self.diagnostic()
        codes = {i["code"] for i in result.report["issues"]}
        self.assertTrue({"SOURCE_CHILD_COUNT_MISMATCH", "SOURCE_LEAF_MISMATCH"} <= codes)

    def test_numeric_leaf_flag_is_not_a_boolean(self):
        self.rows[0]["is_leaf"] = 1
        self.assertFalse(self.diagnostic().report["valid"])

    def test_unknown_columns_are_rejected(self):
        self.rows[0]["private_question"] = "Synthetic disallowed field"
        self.assertFalse(self.diagnostic().report["valid"])

    def test_source_page_id_is_required(self):
        self.rows[0]["source_page_id"] = None
        self.assertFalse(self.diagnostic().report["valid"])

    def test_nested_child_parent_disagreement_is_rejected(self):
        tree = self.tree()
        tree["roots"][0]["children"][0]["parent_id"] = 25
        with self.assertRaises(IngestError):
            flatten_tree(tree)

    def test_nested_envelope_totals_and_book_identity_are_checked(self):
        for field, value in (("total_nodes", 3), ("root_count", 2), ("scope", "other")):
            tree = self.tree()
            tree[field] = value
            with self.subTest(field=field):
                with self.assertRaises(IngestError):
                    flatten_tree(tree)
        tree = self.tree()
        tree["source"]["work_id"] = 21642
        with self.assertRaises(IngestError):
            flatten_tree(tree)

    def test_real_profile_rejects_a_re_pinned_synthetic_owner_format(self):
        path, manifest = self.source()
        manifest = replace(manifest, source_kind="owner_supplied",
                           expected_nodes=11397, expected_roots=32, expected_max_depth=5)
        result = ingest(path, manifest, profile="real-622", input_adapter="owner-622-r1", strict=False)
        self.assertIn("OWNER_R1_INPUT_PIN_MISMATCH", {i["code"] for i in result.report["issues"]})
        self.assertIsNone(result.output_bytes)

    def test_source_paths_must_match_parent_edges_and_original_titles(self):
        self.rows[1]["path_titles"][0] = "Contradictory synthetic title"
        result = self.diagnostic()
        self.assertIn("SOURCE_PATH_MISMATCH", {i["code"] for i in result.report["issues"]})

    def test_invalid_metadata_path_types_are_rejected(self):
        self.rows[1]["path_titles"] = ["Valid synthetic title", {"user": "disallowed object"}]
        self.assertFalse(self.diagnostic().report["valid"])


if __name__ == "__main__":
    unittest.main()
