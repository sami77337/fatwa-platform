"""Exact synthetic row slices remain tied to original UTF-8 input bytes."""

import codecs
import csv
import json
import unittest

from tools.content_intake.cli import MAX_BYTES, MAX_ROWS, SCHEMA, load
from tools.content_intake.provenance import RowSpan, locate_rows


class RowProvenanceTests(unittest.TestCase):
    def assert_spans(self, raw, suffix, expected):
        spans = locate_rows(raw, suffix)
        self.assertIsInstance(spans, tuple)
        self.assertEqual(len(spans), len(load(raw, suffix)))
        self.assertEqual([span.raw for span in spans], expected)
        previous_end = 0
        for span in spans:
            self.assertIsInstance(span, RowSpan)
            self.assertGreaterEqual(span.byte_start, previous_end)
            self.assertEqual(raw[span.byte_start : span.byte_end], span.raw)
            previous_end = span.byte_end
        return spans

    def test_json_values_preserve_escape_spelling_and_utf8_offsets(self):
        rows = [
            '{"question":" سُؤالٌ ","external_id":"s"}',
            '{"question":"\\u0633","nested":[{"items":[1,2]}]}',
            "null",
            "4",
        ]
        raw = codecs.BOM_UTF8 + (" \r\n[ \n" + ", \r\n".join(rows) + "\n ] ").encode()
        spans = self.assert_spans(raw, ".json", [row.encode() for row in rows])
        self.assertEqual(spans[0].byte_start, raw.index(b"{"))

    def test_json_envelope_accepts_both_key_orders_and_empty_array(self):
        for value in (
            {"schema": SCHEMA, "items": [{"question": "سُؤال"}]},
            {"items": [{"question": "سُؤال"}], "schema": SCHEMA},
        ):
            raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
            spans = locate_rows(raw, ".json")
            self.assertEqual(json.loads(spans[0].raw), value["items"][0])
            self.assertEqual(raw[spans[0].byte_start : spans[0].byte_end], spans[0].raw)
        self.assert_spans(b"[ ]", ".json", [])

    def test_jsonl_skips_blank_physical_lines_and_keeps_unicode_separators(self):
        first = '{"question":"س\u2028ص\u2029ع\u0085ق"}\r\n'.encode()
        second = b'  {"external_id":"s"}\r'
        raw = codecs.BOM_UTF8 + b"\r\n \n" + first + b"\r" + second + b"\r"
        self.assert_spans(raw, ".jsonl", [first, second])

    def test_csv_multiline_and_blank_lines_preserve_complete_record(self):
        first = 's," سُؤال\r\nثانٍ "\r\n'.encode()
        second = b't,"quote ""exact"""\r'
        raw = codecs.BOM_UTF8 + b"external_id,question\r\n\r\n" + first + b"\n" + second
        self.assert_spans(raw, ".csv", [first, second])

    def test_csv_retains_extra_and_missing_cells(self):
        self.assert_spans(
            b"external_id,question\ns,synthetic,extra\nt\n",
            ".csv",
            [b"s,synthetic,extra\n", b"t\n"],
        )

    def test_csv_empty_quoted_record_is_not_a_blank_line(self):
        self.assert_spans(b'question\n\n""\n \n', ".csv", [b'""\n', b" \n"])

    def test_json_envelope_nested_items_key_does_not_select_wrong_array(self):
        raw = (
            '{"items":[{"question":"items", "items": [0]}],"schema":' + json.dumps(SCHEMA) + "}"
        ).encode()
        self.assert_spans(raw, ".json", [b'{"question":"items", "items": [0]}'])

    def test_same_malformed_inputs_are_rejected_by_existing_loader(self):
        cases = [
            (b'[{"x":1,"x":2}]', ".json"),
            (b"[NaN]", ".json"),
            (b'[{"x":"\\ud800"}]', ".json"),
            (b"[]", ".txt"),
            (b'{"items":[],"schema":"wrong"}', ".json"),
            (b'question\n"unfinished', ".csv"),
            (b"{}\ninvalid", ".jsonl"),
        ]
        for raw, suffix in cases:
            with self.subTest(raw=raw, suffix=suffix), self.assertRaises((ValueError, csv.Error)):
                locate_rows(raw, suffix)

    def test_input_and_row_bounds_are_existing_loader_bounds(self):
        with self.assertRaises(ValueError):
            locate_rows(b" " * (MAX_BYTES + 1), ".json")
        with self.assertRaises(ValueError):
            locate_rows(b"[" + b",".join([b"{}"] * (MAX_ROWS + 1)) + b"]", ".json")
        raw = b"[" + b",".join([b"{}"] * MAX_ROWS) + b"]"
        self.assertEqual(len(locate_rows(raw, ".json")), MAX_ROWS)
