"""Locate exact source bytes without altering the existing intake adapters.

Offsets are zero-based, with an exclusive end. CSV and JSONL spans include their
physical line terminators; JSON spans cover each complete array value, excluding
surrounding separators. A BOM and skipped blank lines belong to the source file,
not to an individual row. The caller must retain that file's original bytes/SHA.
"""

import codecs
import csv
import io
import json
from dataclasses import dataclass

from .cli import load


@dataclass(frozen=True, slots=True)
class RowSpan:
    byte_start: int
    byte_end: int
    raw: bytes


class _PhysicalLines:
    """Track original UTF-8 lengths while csv.reader consumes multiline records."""

    def __init__(self, text, byte_start):
        self.lines = iter(io.StringIO(text, newline=""))
        self.byte_position = byte_start

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self.lines)
        self.byte_position += len(line.encode("utf-8"))
        return line


def _skip_space(text, position):
    while position < len(text) and text[position] in " \t\r\n":
        position += 1
    return position


def _json_character_spans(text):
    """The existing loader has already validated the complete JSON document."""
    decoder = json.JSONDecoder()
    position = _skip_space(text, 0)
    if text[position] == "{":
        position = _skip_space(text, position + 1)
        while text[position] != "}":
            key, end = decoder.raw_decode(text, position)
            position = _skip_space(text, end)
            position = _skip_space(text, position + 1)  # colon
            if key == "items":
                break
            _, end = decoder.raw_decode(text, position)
            position = _skip_space(text, end)
            if text[position] == ",":
                position = _skip_space(text, position + 1)
    # The array may be the root or the caller's validated envelope.items value.
    position = _skip_space(text, position + 1)
    spans = []
    while text[position] != "]":
        _, end = decoder.raw_decode(text, position)
        spans.append((position, end))
        position = _skip_space(text, end)
        if text[position] == ",":
            position = _skip_space(text, position + 1)
    return spans


def locate_rows(raw: bytes, suffix: str) -> tuple[RowSpan, ...]:
    """Return one exact span per row accepted by ``load(raw, suffix)``.

    This adds no alternate acceptance path: malformed files and byte/row bounds
    are checked by the existing loader before locating any source rows. Row-level
    validation failures remain locatable, including CSV extra/missing cells and
    non-object JSON values. No canonicalization or source correction is applied.
    """
    rows = load(raw, suffix)
    text = raw.decode("utf-8-sig", errors="strict")
    bom_size = len(codecs.BOM_UTF8) if raw.startswith(codecs.BOM_UTF8) else 0
    spans = []
    if suffix == ".json":
        previous_char, previous_byte = 0, bom_size
        for start, end in _json_character_spans(text):
            byte_start = previous_byte + len(text[previous_char:start].encode("utf-8"))
            byte_end = byte_start + len(text[start:end].encode("utf-8"))
            spans.append(RowSpan(byte_start, byte_end, raw[byte_start:byte_end]))
            previous_char, previous_byte = end, byte_end
    elif suffix == ".jsonl":
        lines = _PhysicalLines(text, bom_size)
        for line in lines:
            if line.strip():
                end = lines.byte_position
                start = end - len(line.encode("utf-8"))
                spans.append(RowSpan(start, end, raw[start:end]))
    else:
        lines = _PhysicalLines(text, bom_size)
        reader = csv.reader(lines, strict=True)
        next(reader)  # Validated header; no header row belongs in row reports.
        start = lines.byte_position
        for record in reader:
            end = lines.byte_position
            if record:  # DictReader ignores empty physical records.
                spans.append(RowSpan(start, end, raw[start:end]))
            start = end
    if len(spans) != len(rows):
        raise ValueError("input: row_provenance_alignment_failed")
    return tuple(spans)
