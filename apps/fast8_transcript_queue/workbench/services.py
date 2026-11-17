"""Manual review over the existing transcript contracts, without case writes."""

import csv
import io
import json
from dataclasses import dataclass
from hashlib import sha256
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from apps import transcript_pipeline as pipeline
from apps.fast8_segment_timeline.service import diagnose_file
from apps.fast8_transcript_queue.services import build_transcript_queue

ValidationError = pipeline.ValidationError


@dataclass(frozen=True, slots=True)
class Document:
    original: bytes
    original_suffix: str
    current: bytes
    current_suffix: str
    revision: int = 0


def _rows(raw, suffix):
    if type(raw) is not bytes or not 1 <= len(raw) <= pipeline.MAX_BYTES:
        raise ValidationError("input: invalid_size_or_type")
    if suffix not in {".json", ".csv", ".jsonl"}:
        raise ValidationError("input: unsupported_format")
    try:
        rows = pipeline._load(raw, suffix)
        if not 1 <= len(rows) <= pipeline.MAX_ROWS:
            raise ValidationError("input: invalid_row_count")
        return [pipeline._validated_row(row, i, suffix) for i, row in enumerate(rows, 1)]
    except (ValueError, UnicodeError, csv.Error, RecursionError) as exc:
        raise ValidationError("input: invalid_transcript") from exc


def open_document(raw, suffix, *, synthetic_fixtures_only=False):
    if synthetic_fixtures_only is not True:
        raise ValidationError("input: synthetic_ack_required")
    suffix = suffix.lower()
    _rows(raw, suffix)
    return Document(raw, suffix, raw, suffix)


def review(document):
    """Return recoverable timing findings even while export is blocked."""
    rows = _rows(document.current, document.current_suffix)
    timeline = diagnose_file(
        document.current, document.current_suffix, synthetic_fixtures_only=True
    )
    report = json.loads(timeline.json_bytes())
    queue = None
    queue_error = False
    if report["cues_allowed"]:
        try:
            queue = build_transcript_queue(
                document.current, document.current_suffix, synthetic_fixtures_only=True
            )
        except ValidationError:
            queue_error = True
    return rows, report, queue, queue_error


def revise(document, *, index, start_ms, end_ms, replacement_text=None):
    """Only explicitly edited text changes; timing-only edits preserve CRLF/Unicode."""
    rows = _rows(document.current, document.current_suffix)
    if type(index) is not int or not 0 <= index < len(rows) or document.revision >= 100:
        raise ValidationError("review: invalid_revision_or_segment")
    edited = dict(rows[index], start_ms=start_ms, end_ms=end_ms)
    if replacement_text is not None:
        edited["text"] = replacement_text
    pipeline._validated_row(edited, index + 1, ".json")
    if edited == rows[index]:
        return document
    rows[index] = edited
    current = pipeline._encoded({"schema": pipeline.SCHEMA, "items": rows})
    _rows(current, ".json")
    return Document(
        document.original, document.original_suffix, current, ".json", document.revision + 1
    )


def export_bundle(document):
    """Deterministic ZIP; input bytes retained; no fatwa approval or case association."""
    rows, report, queue, queue_error = review(document)
    if not report["cues_allowed"] or queue is None or queue_error:
        raise ValidationError("export: resolve_findings_first")
    original_rows = _rows(document.original, document.original_suffix)
    if len(original_rows) != len(rows):
        raise ValidationError("export: lineage_mismatch")
    changes = []
    for number, (before, after) in enumerate(zip(original_rows, rows, strict=True), 1):
        if any(
            before[key] != after[key] for key in pipeline.FIELDS - {"text", "start_ms", "end_ms"}
        ):
            raise ValidationError("export: lineage_mismatch")
        fields = [key for key in ("text", "start_ms", "end_ms") if before[key] != after[key]]
        if fields:
            changes.append(
                {
                    "row": number,
                    "source_id": after["source_id"],
                    "segment_id": after["segment_id"],
                    "changed_fields": fields,
                }
            )
    timeline = diagnose_file(
        document.current, document.current_suffix, synthetic_fixtures_only=True
    )
    files = {
        "original" + document.original_suffix: document.original,
        "reviewed" + document.current_suffix: document.current,
        "queue.json": queue.json_bytes(),
        "prepared-questions.json": queue.prepared_bytes(),
        "timeline.json": timeline.json_bytes(),
        "cues.json": timeline.cue_json_bytes(),
    }
    manifest = {
        "schema": "fatwa.transcript-workbench.bundle.v1",
        "synthetic_only": True,
        "revision": document.revision,
        "manual_editing_performed": bool(changes),
        "changes": changes,
        "original_input_sha256": sha256(document.original).hexdigest(),
        "reviewed_input_sha256": sha256(document.current).hexdigest(),
        "case_binding": "NOT_CONNECTED",
        "answer_role": "SOURCE_EVIDENCE_ONLY",
        "publication_allowed": False,
        "approval_granted": False,
        "hashes_are_authentication": False,
        "files": [
            {"name": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in sorted(files.items())
        ],
    }
    files["manifest.json"] = pipeline._encoded(manifest)
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, raw in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw)
    return stream.getvalue()
