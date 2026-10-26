"""Diagnostic adapter over transcript_pipeline; never infer cuts or touch media."""

import csv
import hashlib
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps import transcript_pipeline as pipeline

ValidationError = pipeline.ValidationError
CUE_FIELDS = (
    "source_id",
    "source_sha256",
    "segment_id",
    "segment_sha256",
    "pair_id",
    "kind",
    "question_label",
    "start_ms",
    "end_ms",
    "start_time",
    "end_time",
)
HINTS = {
    "integer_milliseconds_required": "Supply exact integer milliseconds; do not round or coerce.",
    "invalid_interval": "Supply 0 <= start_ms < end_ms <= 86400000 from manual evidence.",
    "duplicate_segment_id": "Assign a unique segment_id within this source after manual review.",
    "duplicate_span": "Review the identical span and remove or correct the duplicate manually.",
    "overlap": "Review both supplied spans; the validator does not choose new boundaries.",
    "gap": "Uncovered interval; review manually. No missing question is inferred.",
    "input_order": "Input records are out of temporal order; cues use chronological order.",
    "ambiguous_pair": "Supply at most one question and one answer for this source/pair_id.",
    "question_required": "Supply the explicitly labelled question for this pair.",
    "answer_must_follow_question": "Review pair timing; answer must start at or after question end.",
    "duration_exceeded": "Review the supplied end against the declared source duration.",
    "answer_not_supplied": "No answer supplied; this does not infer or generate an answer.",
}


def _digest(value: object) -> str:
    # Same canonical bytes as the upstream source revision contract.
    return hashlib.sha256(pipeline._encoded(value)).hexdigest()


def _time(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"


@dataclass(frozen=True, slots=True)
class TimelineReport:
    _json: bytes
    _cues: bytes | None

    def json_bytes(self) -> bytes:
        return self._json

    def cue_json_bytes(self) -> bytes:
        if self._cues is None:
            raise ValidationError("cues: resolve_errors_before_manual_export")
        return self._cues

    def cue_csv_bytes(self) -> bytes:
        cues = json.loads(self.cue_json_bytes())["cues"]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=("mode", *CUE_FIELDS), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows({"mode": "MANUAL", **cue} for cue in cues)
        # Exact fields, including CRLF and leading whitespace, are never normalized.
        return stream.getvalue().encode("utf-8")


def diagnose_file(
    raw: bytes,
    suffix: str,
    *,
    synthetic_fixtures_only: bool = False,
    source_durations_ms: dict[str, int] | None = None,
) -> TimelineReport:
    """Diagnose bounded original transcript input; invalid cuts cannot export cues.

    Upstream row/parser helpers are deliberately reused, including strict Unicode,
    CSV integer tokens and input bounds. A complete error-free timeline must also
    pass segment_file. Source digests refer to supplied transcript rows, not media.
    Optional durations are caller-declared bounds, never measured media facts.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("timeline: synthetic_fixture_acknowledgement_required")
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= pipeline.MAX_BYTES:
        raise ValidationError("input: invalid_size_or_type")
    if not isinstance(suffix, str) or suffix.lower() not in {".csv", ".json", ".jsonl"}:
        raise ValidationError("input: unsupported_format")
    suffix = suffix.lower()
    try:
        loaded = pipeline._load(raw, suffix)
    except (ValueError, UnicodeError, csv.Error, RecursionError) as exc:
        raise ValidationError("input: malformed_or_over_limit") from exc
    if not 1 <= len(loaded) <= pipeline.MAX_ROWS:
        raise ValidationError("input: expected_1_to_1000_segments")
    for row in loaded:
        if not isinstance(row, dict) or set(row) != pipeline.FIELDS:
            raise ValidationError("input: exact_fields_required")
        marker = row["fabricated"]
        if (suffix == ".csv" and marker != "true") or (suffix != ".csv" and marker is not True):
            raise ValidationError("input: fabricated_true_required")

    findings: list[dict[str, Any]] = []

    def finding(code, row=None, related=None, source=None, severity="error", **detail):
        findings.append(
            dict(
                code=code,
                severity=severity,
                row=row,
                related_row=related,
                source_id=source,
                message=HINTS.get(
                    code, "Correct the indicated field using the transcript contract."
                ),
                **detail,
            )
        )

    rows: list[tuple[int, dict[str, Any]]] = []
    for number, value in enumerate(loaded, 1):
        try:
            row = pipeline._validated_row(value, number, suffix)
        except ValidationError as exc:
            path, code = str(exc).split(": ", 1)
            finding(code, number, field=path)
        else:
            rows.append((number, row))

    sources = defaultdict(list)
    pairs = defaultdict(list)
    for number, row in rows:
        sources[row["source_id"]].append((number, row))
        pairs[(row["source_id"], row["pair_id"])].append((number, row))
    durations = {} if source_durations_ms is None else source_durations_ms
    known_sources = {r["source_id"] for r in loaded if isinstance(r["source_id"], str)}
    if not isinstance(durations, dict) or any(
        not isinstance(key, str)
        or key not in known_sources
        or type(value) is not int
        or not 0 < value <= pipeline.MAX_TIMESTAMP_MS
        for key, value in durations.items()
    ):
        raise ValidationError("durations: known_sources_and_bounded_integer_milliseconds_required")

    # Do not present partial-source hashes, gaps or pair conclusions as complete.
    complete_rows = len(rows) == len(loaded)
    source_reports = []
    source_hashes = {}
    if complete_rows:
        for source_id, source_rows in sorted(sources.items()):
            ordered = sorted(
                source_rows,
                key=lambda item: (
                    item[1]["start_ms"],
                    item[1]["end_ms"],
                    item[1]["segment_id"],
                    item[0],
                ),
            )
            source_hashes[source_id] = _digest([r for _, r in ordered])
            duration = durations.get(source_id)
            source_reports.append(
                dict(
                    source_id=source_id,
                    source_sha256=source_hashes[source_id],
                    duration_ms=duration,
                    duration_status="DECLARED" if duration is not None else "NOT_SUPPLIED",
                )
            )
            if [n for n, _ in source_rows] != [n for n, _ in ordered]:
                finding("input_order", source=source_id, severity="warning")
            seen_ids, seen_spans = {}, {}
            frontier, frontier_row = 0, None
            for number, row in ordered:
                start, end = row["start_ms"], row["end_ms"]
                identity, span = row["segment_id"], (start, end)
                if identity in seen_ids:
                    finding("duplicate_segment_id", number, seen_ids[identity], source_id)
                if span in seen_spans:
                    finding("duplicate_span", number, seen_spans[span], source_id)
                seen_ids.setdefault(identity, number)
                seen_spans.setdefault(span, number)
                if start < frontier:
                    finding(
                        "overlap",
                        number,
                        frontier_row,
                        source_id,
                        start_ms=start,
                        end_ms=min(end, frontier),
                    )
                elif start > frontier:
                    finding(
                        "gap",
                        number,
                        frontier_row,
                        source_id,
                        "warning",
                        start_ms=frontier,
                        end_ms=start,
                    )
                if end > frontier:
                    frontier, frontier_row = end, number
                if duration is not None and end > duration:
                    finding("duration_exceeded", number, source=source_id, duration_ms=duration)
            if duration is not None and frontier < duration:
                finding(
                    "gap",
                    related=frontier_row,
                    source=source_id,
                    severity="warning",
                    start_ms=frontier,
                    end_ms=duration,
                )

        for (source_id, _), pair in sorted(pairs.items()):
            questions = [(n, r) for n, r in pair if r["kind"] == "question"]
            answers = [(n, r) for n, r in pair if r["kind"] == "answer"]
            for members in (questions, answers):
                for number, _ in members[1:]:
                    finding("ambiguous_pair", number, members[0][0], source_id)
            if not questions:
                finding("question_required", pair[0][0], source=source_id)
            elif len(questions) == 1 and len(answers) == 1:
                if answers[0][1]["start_ms"] < questions[0][1]["end_ms"]:
                    finding(
                        "answer_must_follow_question", answers[0][0], questions[0][0], source_id
                    )
            if questions and not answers:
                finding("answer_not_supplied", questions[0][0], source=source_id, severity="info")

    errors = any(f["severity"] == "error" for f in findings)
    cues = None
    contract_status = "NOT_RUN"
    if not errors:
        # Authoritative existing domain service remains the final acceptance boundary.
        baseline = json.loads(
            pipeline.segment_file(
                raw,
                suffix,
                synthetic_fixtures_only=True,
            ).json_bytes()
        )
        if any(source_hashes[s["source_id"]] != s["source_sha256"] for s in baseline["sources"]):
            raise ValidationError("timeline: upstream_digest_mismatch")
        contract_status = "PASS"
        labels = {
            (r["source_id"], r["pair_id"]): r["text"] for _, r in rows if r["kind"] == "question"
        }
        cues = []
        for _, row in sorted(
            rows,
            key=lambda item: (
                item[1]["source_id"],
                item[1]["start_ms"],
                item[1]["end_ms"],
                item[1]["segment_id"],
            ),
        ):
            cues.append(
                {
                    key: row[key]
                    for key in (
                        "source_id",
                        "segment_id",
                        "pair_id",
                        "kind",
                        "start_ms",
                        "end_ms",
                    )
                }
                | dict(
                    source_sha256=source_hashes[row["source_id"]],
                    segment_sha256=_digest(row),
                    question_label=labels[(row["source_id"], row["pair_id"])],
                    start_time=_time(row["start_ms"]),
                    end_time=_time(row["end_ms"]),
                )
            )
    identity = hashlib.sha256(raw).hexdigest()
    report = dict(
        schema="fatwa.synthetic-segment-timeline.report.v1",
        input_sha256=identity,
        input_format=suffix,
        synthetic_only=True,
        mode="MANUAL",
        cues_allowed=not errors,
        contract_status=contract_status,
        source_digest_status="COMPLETE" if complete_rows else "NOT_RUN",
        findings=findings,
        sources=source_reports,
        segments=[
            dict(row, row_number=number, segment_sha256=_digest(row)) for number, row in rows
        ],
        declared_durations_ms=durations,
        media_status="NOT_CONNECTED",
        publication_allowed=False,
        gates={
            "B": "NOT_PASSED",
            "C": "HOLD",
            "D": "HOLD",
            "E": "HOLD",
            "Phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
            "U03": "OWNER_APPROVAL_PENDING",
            "U10": "OWNER_APPROVAL_PENDING",
        },
    )
    cue_payload = (
        None
        if cues is None
        else pipeline._encoded(
            dict(
                schema="fatwa.synthetic-segment-timeline.cues.v1",
                mode="MANUAL",
                input_sha256=identity,
                declared_durations_ms=durations,
                cues=cues,
            )
        )
    )
    return TimelineReport(pipeline._encoded(report), cue_payload)
