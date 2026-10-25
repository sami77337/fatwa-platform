"""Offline, explicitly fabricated manual transcript cuts; no media, AI or writes."""

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps.fatwa_drafts.intake import ValidationError, text
from tools.content_intake.cli import MAX_BYTES, MAX_ROWS, bounded_rows, parse_json
from tools.content_intake.cli import SCHEMA as PREPARED_SCHEMA

SCHEMA = "fatwa.synthetic-transcript.v1"
MAX_TIMESTAMP_MS = 86_400_000
FIELDS = frozenset(
    {
        "source_id",
        "segment_id",
        "pair_id",
        "kind",
        "start_ms",
        "end_ms",
        "text",
        "provenance",
        "fabricated",
    }
)


def _encoded(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class TranscriptBatch:
    """Immutable validated snapshots; report retains answers and source provenance."""

    _report_bytes: bytes
    _prepared_bytes: bytes

    def json_bytes(self) -> bytes:
        return self._report_bytes

    def prepared_bytes(self) -> bytes:
        """FAST4 question-only intake; no clip, citations or scholarly approvals."""
        return self._prepared_bytes


def _load(raw: bytes, suffix: str) -> list[Any]:
    decoded = raw.decode("utf-8-sig", errors="strict")
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)) or set(headers) != FIELDS:
            raise ValidationError("input: invalid_csv_columns")
        return bounded_rows(reader)
    if suffix == ".jsonl":
        # Preserve Unicode line separators inside text; only CR/LF delimit records.
        return bounded_rows(
            parse_json(line) for line in io.StringIO(decoded, newline="") if line.strip()
        )
    value = parse_json(decoded)
    if isinstance(value, dict):
        if set(value) != {"schema", "items"} or value["schema"] != SCHEMA:
            raise ValidationError("input: invalid_envelope")
        value = value["items"]
    if not isinstance(value, list):
        raise ValidationError("input: expected_array")
    return bounded_rows(value)


def _validated_row(value: object, number: int, suffix: str) -> dict[str, Any]:
    path = f"segments.{number}"
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValidationError(f"{path}: exact_fields_required")
    row = dict(value)
    if suffix == ".csv":
        if row["fabricated"] != "true":
            raise ValidationError(f"{path}.fabricated: true_required")
        row["fabricated"] = True
        for field in ("start_ms", "end_ms"):
            token = row[field]
            if not isinstance(token, str) or not re.fullmatch(r"0|[1-9][0-9]{0,7}", token):
                raise ValidationError(f"{path}.{field}: integer_milliseconds_required")
            row[field] = int(token)
    if row["fabricated"] is not True:
        raise ValidationError(f"{path}.fabricated: true_required")
    for field in ("source_id", "segment_id", "pair_id"):
        identity = text(row[field], f"{path}.{field}", limit=100)
        if identity != identity.strip() or any(
            unicodedata.category(char).startswith("C") for char in identity
        ):
            raise ValidationError(f"{path}.{field}: invalid_identity")
    text(row["text"], f"{path}.text", limit=20_000)
    text(row["provenance"], f"{path}.provenance", limit=500)
    if row["kind"] not in ("question", "answer"):
        raise ValidationError(f"{path}.kind: manual_question_or_answer_required")
    start, end = row["start_ms"], row["end_ms"]
    if type(start) is not int or type(end) is not int:
        raise ValidationError(f"{path}: integer_milliseconds_required")
    if not 0 <= start < end <= MAX_TIMESTAMP_MS:
        raise ValidationError(f"{path}: invalid_interval")
    return row


def _group_and_validate(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], dict[str, dict[str, Any]]]]:
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pairs: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, 1):
        segment_key = (row["source_id"], row["segment_id"])
        if segment_key in seen:
            raise ValidationError(f"segments.{number}: duplicate_segment_id")
        seen.add(segment_key)
        sources[row["source_id"]].append(row)
        pair = pairs[(row["source_id"], row["pair_id"])]
        if row["kind"] in pair:
            raise ValidationError(f"segments.{number}: ambiguous_pair")
        pair[row["kind"]] = row
    for source_rows in sources.values():
        source_rows.sort(key=lambda row: (row["start_ms"], row["end_ms"], row["segment_id"]))
        for previous, current in zip(source_rows, source_rows[1:]):
            if current["start_ms"] < previous["end_ms"]:
                raise ValidationError("segments: overlapping_cuts")
    for pair in pairs.values():
        if "question" not in pair:
            raise ValidationError("pairs: question_required")
        if "answer" in pair and pair["answer"]["start_ms"] < pair["question"]["end_ms"]:
            raise ValidationError("pairs: answer_must_follow_question")
    return dict(sources), dict(pairs)


def segment_file(
    raw: bytes, suffix: str, *, synthetic_fixtures_only: bool = False
) -> TranscriptBatch:
    """Validate manually supplied cuts and export deterministically, entirely in memory.

    The caller must explicitly attest that all text is fabricated. This is not a
    private-data detector. Timestamps are integer milliseconds on each source's
    own timeline. Input file hash covers exact bytes; per-source hash covers the
    sorted validated transcript rows, never an unavailable recording.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("pipeline: synthetic_fixture_acknowledgement_required")
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValidationError("input: invalid_size_or_type")
    if not isinstance(suffix, str) or suffix.lower() not in {".csv", ".json", ".jsonl"}:
        raise ValidationError("input: unsupported_format")
    suffix = suffix.lower()
    try:
        loaded = _load(raw, suffix)
    except (ValueError, UnicodeError, csv.Error, RecursionError) as exc:
        raise ValidationError("input: malformed_or_over_limit") from exc
    if not 1 <= len(loaded) <= MAX_ROWS:
        raise ValidationError("input: expected_1_to_1000_segments")
    rows = [_validated_row(row, number, suffix) for number, row in enumerate(loaded, 1)]
    sources, pairs = _group_and_validate(rows)
    source_hashes = {
        source_id: hashlib.sha256(_encoded(source_rows)).hexdigest()
        for source_id, source_rows in sorted(sources.items())
    }
    items, pair_reports = [], []
    for (source_id, pair_id), pair in sorted(pairs.items()):
        # Bind the export identity to the complete source revision and explicit pair.
        external_id = (
            "transcript-"
            + hashlib.sha256(_encoded([source_id, source_hashes[source_id], pair_id])).hexdigest()
        )
        question, answer = pair["question"], pair.get("answer")
        items.append(
            dict(
                external_id=external_id,
                question=question["text"],
                prepared_clip_url="",
                staff_notes="",
                reference_links=[],
            )
        )
        pair_reports.append(
            dict(
                source_id=source_id,
                source_sha256=source_hashes[source_id],
                pair_id=pair_id,
                external_id=external_id,
                question_segment_id=question["segment_id"],
                answer_segment_id=answer["segment_id"] if answer else None,
                status="manually-paired" if answer else "answer-not-supplied",
            )
        )
    prepared = _encoded(dict(schema=PREPARED_SCHEMA, items=items))
    if len(prepared) > MAX_BYTES:
        raise ValidationError("export: prepared_byte_limit_exceeded")
    report = dict(
        schema="fatwa.synthetic-transcript.report.v1",
        input_sha256=hashlib.sha256(raw).hexdigest(),
        input_format=suffix,
        synthetic_only=True,
        segmentation="manual",
        human_editing_performed=False,
        publication_allowed=False,
        gates={
            "B": "NOT_PASSED",
            "C": "HOLD",
            "D": "HOLD",
            "E": "HOLD",
            "Phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
        },
        sources=[
            dict(source_id=source_id, source_sha256=digest, segment_count=len(sources[source_id]))
            for source_id, digest in source_hashes.items()
        ],
        segments=rows,
        pairs=pair_reports,
        preparation=dict(
            schema=PREPARED_SCHEMA,
            export_sha256=hashlib.sha256(prepared).hexdigest(),
            answer_exported=False,
            media_link_supplied=False,
            review_required=True,
            reference_verification="unverified",
        ),
    )
    return TranscriptBatch(_encoded(report), prepared)
