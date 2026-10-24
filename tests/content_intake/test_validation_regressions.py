"""Synthetic validation regressions; no network, database, or private source data."""

import csv
import io
import json
import unittest

from tools.content_intake.cli import artifacts, load, normalize


def record(**changes):
    return {
        "external_id": "SYN-VALIDATION",
        "question": "سؤال اصطناعي فقط؟",
        "prepared_clip_url": "https://example.invalid/clip",
        "staff_notes": "",
        "reference_links": [],
        **changes,
    }


class ValidationRegressions(unittest.TestCase):
    def test_every_duplicate_is_rejected_even_when_later_row_has_other_errors(self):
        items, findings = normalize(
            [record(), record(question=""), record(external_id="SYN-UNIQUE")]
        )
        self.assertEqual([item["external_id"] for item in items], ["SYN-UNIQUE"])
        self.assertEqual([f["row"] for f in findings if f["code"] == "duplicate_id"], [1, 2])
        self.assertIn(
            {"row": 2, "field": "question", "code": "required", "severity": "error"}, findings
        )

    def test_non_string_ids_do_not_create_false_duplicates(self):
        items, findings = normalize([record(external_id=None), record(external_id=[])])
        self.assertEqual(items, [])
        self.assertNotIn("duplicate_id", [f["code"] for f in findings])

    def test_all_independent_fields_report_length_and_content_errors(self):
        row = record(
            external_id=" " + "i" * 100 + "\x01",
            question="q" * 20000 + "\x01",
            title="t" * 20000 + "\x01",
            staff_notes="n" * 20000 + "\x01",
            prepared_clip_url="invalid:" + "u" * 2048,
            reference_links=[{"source_id": "missing-heading"}],
            unknown="synthetic",
        )
        items, findings = normalize([row])
        self.assertEqual(items, [])
        pairs = {(f["field"], f["code"]) for f in findings}
        for field, maximum in (
            ("external_id", 100),
            ("question", 20000),
            ("title", 20000),
            ("staff_notes", 20000),
            ("prepared_clip_url", 2048),
        ):
            self.assertIn((field, f"too_long_max_{maximum}"), pairs)
        for field in ("external_id", "question", "title", "staff_notes"):
            self.assertIn((field, "invalid_unicode_or_control"), pairs)
        self.assertTrue(
            {
                ("external_id", "id_whitespace_not_allowed"),
                ("title", "ambiguous_title_question"),
                ("prepared_clip_url", "invalid_http_url"),
                ("reference_links", "expected_source_id_heading_id_string_pairs"),
                ("", "unknown_columns_or_extra_cells"),
            }
            <= pairs
        )

    def test_text_at_each_exact_limit_preserves_unicode_and_crlf(self):
        row = record(
            external_id="i" * 100,
            question="ع" * 19996 + "\r\n\t ",
            staff_notes="ن" * 19998 + "\r\n",
            prepared_clip_url="http://example.invalid:8080/" + "u" * 2020,
        )
        self.assertEqual(len(row["prepared_clip_url"]), 2048)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow({**row, "reference_links": "[]"})
        for raw, suffix in (
            (stream.getvalue().encode("utf-8"), ".csv"),
            (json.dumps([row]).encode(), ".json"),
            (json.dumps(row).encode(), ".jsonl"),
        ):
            with self.subTest(suffix=suffix):
                outputs, manifest = artifacts(raw, suffix)
                self.assertEqual(manifest["status"], "VALID")
                self.assertEqual(json.loads(outputs["intake.json"])["items"], [row])

    def test_each_limit_plus_one_is_rejected_independently(self):
        for field, value in (
            ("external_id", "i" * 101),
            ("question", "ع" * 20001),
            ("staff_notes", "ن" * 20001),
            ("prepared_clip_url", "https://example.invalid/" + "u" * 2025),
        ):
            with self.subTest(field=field):
                items, findings = normalize([record(**{field: value})])
                self.assertEqual(items, [])
                self.assertTrue(
                    any(f["field"] == field and f["code"].startswith("too_long_") for f in findings)
                )

    def test_title_alias_requires_exact_original_when_question_is_present(self):
        for title in ("سؤال اصطناعي فقط؟ ", "\tسؤال اصطناعي فقط؟", "سؤال اصطناعي فقط؟\r\n"):
            with self.subTest(title=title):
                items, findings = normalize([record(title=title)])
                self.assertEqual(items, [])
                self.assertIn("ambiguous_title_question", [f["code"] for f in findings])

    def test_identical_title_alias_remains_valid(self):
        original = " \tسؤال\r\nاصطناعي؟ "
        items, findings = normalize([record(question=original, title=original)])
        self.assertEqual(items[0]["question"], original)
        self.assertEqual(findings, [])

    def test_missing_optional_csv_cells_are_named_without_losing_other_errors(self):
        raw = b"external_id,question,prepared_clip_url,staff_notes,reference_links\r\nSYN-CSV,,ftp://example.invalid\r\n"
        rows = load(raw, ".csv")
        self.assertEqual(rows[0]["staff_notes"], None)
        items, findings = normalize(rows)
        self.assertEqual(items, [])
        self.assertEqual(
            {f["field"] for f in findings if f["code"] == "csv_missing_cell"},
            {"staff_notes", "reference_links"},
        )
        self.assertIn("required", [f["code"] for f in findings])
        self.assertIn("invalid_http_url", [f["code"] for f in findings])

    def test_extra_csv_cells_are_actionable_and_do_not_echo_submitted_text(self):
        _, manifest = artifacts(
            b"external_id,question\r\nSYN-CSV,synthetic,SYN-SECRET,other\r\n", ".csv"
        )
        self.assertEqual(manifest["status"], "INVALID")
        self.assertIn(
            {"row": 1, "field": "", "code": "csv_extra_cells", "severity": "error"},
            manifest["findings"],
        )
        self.assertNotIn("SYN-SECRET", json.dumps(manifest))

    def test_csv_missing_cell_findings_remain_bounded_by_row_and_column_limits(self):
        raw = (
            "external_id,question,prepared_clip_url,staff_notes,reference_links\n"
            + "".join(f"SYN-{n},synthetic\n" for n in range(1000))
        ).encode()
        _, manifest = artifacts(raw, ".csv")
        self.assertEqual(manifest["row_count"], 1000)
        self.assertEqual(manifest["valid_row_count"], 0)
        self.assertEqual(sum(f["code"] == "csv_missing_cell" for f in manifest["findings"]), 3000)
        self.assertLessEqual(len(manifest["findings"]), 10000)


if __name__ == "__main__":
    unittest.main()
