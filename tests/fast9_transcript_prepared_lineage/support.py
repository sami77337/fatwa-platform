"""Fabricated Q/A only; reused IDs deliberately exercise cross-source joins."""

import csv
import io
import json
from hashlib import sha256
from pathlib import Path

from apps.transcript_pipeline import segment_file

FIXTURES = Path(__file__).parent / "fixtures"


def rows():
    result = []
    for source in ("مصدر-مختلق-٩", "fabricated-source-b"):
        for kind, segment, start, end, text in (
            ("question", "q-مشترك", 17, 1017, "  سُؤالٌ تَجريبيّ مُختلق\r\nبلا حكم شرعي؟\u2028  "),
            (
                "answer",
                "a-مشترك",
                1023,
                2029,
                "  نَصّ اصطناعي لا يمثّل جوابًا شرعيًا.\r\nللاختبار فقط.  ",
            ),
        ):
            result.append(
                dict(
                    source_id=source,
                    segment_id=segment,
                    pair_id="pair-shared",
                    kind=kind,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    provenance="FAST9 fabricated manual spans; no media or real case",
                    fabricated=True,
                )
            )
    return result


def encode(values, suffix=".json"):
    if suffix == ".csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(values[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(dict(row, fabricated="true") for row in values)
        return stream.getvalue().encode("utf-8")
    if suffix == ".jsonl":
        return ("\r\n".join(json.dumps(row, ensure_ascii=False) for row in values) + "\r\n").encode(
            "utf-8"
        )
    return (json.dumps(values, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n").encode(
        "utf-8"
    )


def arguments(raw, suffix=".json"):
    report = json.loads(segment_file(raw, suffix, synthetic_fixtures_only=True).json_bytes())
    return dict(
        expected_input_sha256=sha256(raw).hexdigest(),
        expected_sources={s["source_id"]: s["source_sha256"] for s in report["sources"]},
        synthetic_fixtures_only=True,
    )
