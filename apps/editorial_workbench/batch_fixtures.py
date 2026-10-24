"""Invented, deterministic UTF-8 files held in memory; never discovers user data."""

import csv
import io
import json

from apps.prepared_pipeline.batches import PreparedInput


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def synthetic_inputs() -> tuple[PreparedInput, ...]:
    """Explicit source ordering is stable, including rejected and malformed inputs."""
    pointer = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}

    def row(identity, question="سؤالٌ اصطناعي للتجربة", **changes):
        return dict(
            external_id=identity,
            question=question,
            prepared_clip_url="https://example.invalid/synthetic-prepared.mp4",
            reference_links=[pointer],
            **changes,
        )

    csv_rows = [
        row("SYN-CSV-1", "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "),
        row("SYN-SHARED", "نسخة CSV اصطناعية مكررة"),
        row("SYN-PENDING"),
        row("SYN-OVERFLOW"),
    ]
    csv_rows[2]["prepared_clip_url"] = ""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(("external_id", "question", "prepared_clip_url", "reference_links"))
    for index, item in enumerate(csv_rows):
        values = [
            item["external_id"],
            item["question"],
            item["prepared_clip_url"],
            _json(item["reference_links"]),
        ]
        writer.writerow(values + (["overflow-synthetic"] if index == 3 else []))
    unknown = row("SYN-JSON-2")
    unknown["reference_links"] = [{"source_id": "UNKNOWN-SYNTHETIC", "heading_id": "UNKNOWN"}]
    invalid = row("SYN-INVALID")
    invalid.update(prepared_clip_url="http://example.invalid/invalid", reference_links=42)
    json_rows = [row("SYN-SHARED", "نسخة JSON اصطناعية مكررة"), unknown, invalid, None]
    no_refs = row("SYN-JSONL-1", "سؤال اصطناعي بلا إحالات؛ لا تُخترع مراجع")
    no_refs["reference_links"] = []
    title_only = row("SYN-TITLE")
    del title_only["question"]
    title_only["title"] = "  عنوانٌ اصطناعي محفوظ  "
    invalid_pointer = row("SYN-POINTER")
    invalid_pointer["reference_links"] = [
        {"source_id": " W7-SOURCE", "heading_id": "W7-HEADING-1"},
        {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-2"},
    ]
    return (
        PreparedInput("synthetic-csv", stream.getvalue().encode(), ".csv"),
        PreparedInput("synthetic-json", _json(json_rows).encode(), ".json"),
        PreparedInput(
            "synthetic-jsonl",
            ("\n".join(map(_json, [no_refs, title_only, invalid_pointer])) + "\n").encode(),
            ".jsonl",
        ),
        PreparedInput("synthetic-malformed", b'{"synthetic":', ".json"),
    )
