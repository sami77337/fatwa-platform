"""Fabricated records only. Serializers create inputs, never validate or repair them."""

import codecs
import csv
import hashlib
import io
import json

FORMATS = (".csv", ".json", ".jsonl")
ORIGINAL = ' \tأَثَرٌ ا\u0654صطناعي ـ ي ى ك ک\r\n"سطر، ثانٍ"\u2028ثالث\u2029رابع  '
MARKER = "SYNTHETIC-DIAGNOSTIC-CANARY"


def intake_row(identity="SYN-FAST8-أ", **changes):
    return {
        "external_id": identity,
        "question": ORIGINAL,
        "prepared_clip_url": "https://example.invalid/synthetic-only.mp4",
        "staff_notes": " \tسجل اختبار مُصطنع\r\n ",
        "reference_links": [],
        **changes,
    }


def segment_row(**changes):
    return {
        "source_id": "SYN-FAST8-source-أ",
        "segment_id": "segment-1",
        "pair_id": "pair-1",
        "kind": "question",
        "start_ms": 123,
        "end_ms": 456,
        "text": ORIGINAL,
        "provenance": "FAST8-explicitly-fabricated-no-recording-v1",
        "fabricated": True,
        **changes,
    }


def encode(rows, suffix, *, bom=True):
    """Use CRLF framing; include a BOM by default in every supported format."""
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            cells = dict(row)
            if "reference_links" in cells and isinstance(cells["reference_links"], list):
                cells["reference_links"] = json.dumps(cells["reference_links"], ensure_ascii=False)
            if cells.get("fabricated") is True:
                cells["fabricated"] = "true"
            writer.writerow(cells)
        body = stream.getvalue()
    elif suffix == ".json":
        body = json.dumps(rows, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n"
    elif suffix == ".jsonl":
        body = "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\r\n"
    else:
        raise ValueError("Fixture format unsupported")
    return (codecs.BOM_UTF8 if bom else b"") + body.encode("utf-8")


def fixture_inventory():
    """Identities for the six seed files; tests name their derived mutations."""
    return [
        {
            "identity": f"FAST8-fabricated-{kind}-bom-crlf-v1{suffix}",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for kind, row in (("intake", intake_row()), ("transcript", segment_row()))
        for suffix in FORMATS
        for raw in (encode([row], suffix),)
    ]
