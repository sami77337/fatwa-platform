"""Manual review over the existing transcript contracts, without case writes."""

import csv
import io
import json
from dataclasses import dataclass
from hashlib import sha256
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from apps import transcript_pipeline as pipeline
from apps.fast8_segment_timeline.service import diagnose_file
from apps.fast8_transcript_queue.services import build_transcript_queue

ValidationError = pipeline.ValidationError
MAX_BUNDLE_BYTES = 16_000_000


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


def pairing_options(document, index):
    """Offer unambiguous same-source questions; do not infer a semantic match."""
    rows = _rows(document.current, document.current_suffix)
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValidationError("pairing: invalid_segment")
    answer = rows[index]
    if answer["kind"] != "answer":
        return []
    options = []
    for number, question in enumerate(rows):
        if question["kind"] != "question" or question["source_id"] != answer["source_id"]:
            continue
        members = [
            row
            for row in rows
            if row["source_id"] == question["source_id"] and row["pair_id"] == question["pair_id"]
        ]
        if sum(row["kind"] == "question" for row in members) != 1:
            continue
        occupied = any(row["kind"] == "answer" and row is not answer for row in members)
        options.append(
            {
                "index": number,
                "question": question,
                "occupied": occupied,
                "current": question["pair_id"] == answer["pair_id"],
                "timing_compatible": answer["start_ms"] >= question["end_ms"],
            }
        )
    return options


def relink_answer(document, *, index, question_index):
    """Human-selected pair only. Preserve source, segment, role, text and timestamps."""
    if type(question_index) is not int or document.revision >= 100:
        raise ValidationError("pairing: invalid_target_or_revision")
    option = next(
        (item for item in pairing_options(document, index) if item["index"] == question_index), None
    )
    if option is None or option["occupied"]:
        raise ValidationError("pairing: unavailable_question")
    if option["current"]:
        return document
    rows = _rows(document.current, document.current_suffix)
    rows[index]["pair_id"] = option["question"]["pair_id"]
    current = pipeline._encoded({"schema": pipeline.SCHEMA, "items": rows})
    _rows(current, ".json")
    return Document(
        document.original, document.original_suffix, current, ".json", document.revision + 1
    )


def document_changes(document):
    """Compare the exact original with current rows, retaining immutable identities."""
    rows = _rows(document.current, document.current_suffix)
    original_rows = _rows(document.original, document.original_suffix)
    if len(original_rows) != len(rows):
        raise ValidationError("export: lineage_mismatch")
    changes = []
    for number, (before, after) in enumerate(zip(original_rows, rows, strict=True), 1):
        mutable = {"text", "start_ms", "end_ms"}
        if before["kind"] == "answer":
            mutable.add("pair_id")
        if any(before[key] != after[key] for key in pipeline.FIELDS - mutable):
            raise ValidationError("export: lineage_mismatch")
        fields = [
            key for key in ("text", "start_ms", "end_ms", "pair_id") if before[key] != after[key]
        ]
        if fields:
            changes.append(
                {
                    "row": number,
                    "source_id": after["source_id"],
                    "segment_id": after["segment_id"],
                    "changed_fields": fields,
                }
            )
            if "pair_id" in fields:
                changes[-1]["original_pair_id"] = before["pair_id"]
                changes[-1]["reviewed_pair_id"] = after["pair_id"]
    return changes


def _schema(kind, changes):
    version = 2 if any("pair_id" in change["changed_fields"] for change in changes) else 1
    return f"fatwa.transcript-workbench.{kind}.v{version}"


def export_bundle(document):
    """Deterministic ZIP; input bytes retained; no fatwa approval or case association."""
    rows, report, queue, queue_error = review(document)
    if not report["cues_allowed"] or queue is None or queue_error:
        raise ValidationError("export: resolve_findings_first")
    changes = document_changes(document)
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
        "schema": _schema("bundle", changes),
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
    return _archive(files)


def _archive(files):
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, raw in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw)
    raw = stream.getvalue()
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValidationError("export: bundle_too_large")
    return raw


def checkpoint(document):
    """Save a resumable work-in-progress, including unresolved timeline errors."""
    changes = document_changes(document)
    files = {
        "original" + document.original_suffix: document.original,
        "reviewed" + document.current_suffix: document.current,
    }
    manifest = {
        "schema": _schema("checkpoint", changes),
        "synthetic_only": True,
        "revision": document.revision,
        "manual_editing_performed": bool(changes),
        "changes": changes,
        "case_binding": "NOT_CONNECTED",
        "approval_granted": False,
        "publication_allowed": False,
        "hashes_are_authentication": False,
        "files": [
            {"name": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in sorted(files.items())
        ],
    }
    files["manifest.json"] = pipeline._encoded(manifest)
    return _archive(files)


def _read_archive(raw):
    """Read only our bounded stored-member format, never extract anything to disk."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BUNDLE_BYTES:
        raise ValidationError("bundle: invalid_size")
    allowed = {
        prefix + suffix
        for prefix in ("original", "reviewed")
        for suffix in (".json", ".csv", ".jsonl")
    } | {"manifest.json", "queue.json", "prepared-questions.json", "timeline.json", "cues.json"}
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                len(members) not in (3, 7)
                or len({item.filename for item in members}) != len(members)
                or sum(item.file_size for item in members) > MAX_BUNDLE_BYTES
            ):
                raise ValidationError("bundle: invalid_members")
            files = {}
            for item in members:
                limit = (
                    pipeline.MAX_BYTES
                    if item.filename.startswith(("original", "reviewed"))
                    else MAX_BUNDLE_BYTES
                )
                if (
                    item.filename not in allowed
                    or item.compress_type != ZIP_STORED
                    or item.flag_bits & 1
                    or not 0 <= item.file_size <= limit
                    or item.compress_size != item.file_size
                    or (item.external_attr >> 16) & 0o170000 not in (0, 0o100000)
                ):
                    raise ValidationError("bundle: invalid_member")
                with archive.open(item) as source:
                    files[item.filename] = source.read(limit + 1)
                if len(files[item.filename]) != item.file_size:
                    raise ValidationError("bundle: invalid_member_size")
            return files
    except (BadZipFile, OSError, RuntimeError, ValueError, NotImplementedError) as exc:
        raise ValidationError("bundle: invalid_archive") from exc


def restore_bundle(raw, *, synthetic_fixtures_only=False):
    """Resume an unsigned artifact after reconstructing every derived byte locally.

    This checks internal consistency, not authorship or trusted case authority.
    Neither manifests nor prepared reports are passed through as authoritative data.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("bundle: synthetic_ack_required")
    files = _read_archive(raw)
    try:
        manifest = pipeline.parse_json(files["manifest.json"].decode("utf-8"))
        if type(manifest) is not dict:
            raise ValueError("manifest")
        revision = manifest["revision"]
        if type(revision) is not int or not 0 <= revision <= 100:
            raise ValueError("revision")
        originals = [name for name in files if name.startswith("original.")]
        currents = [name for name in files if name.startswith("reviewed.")]
        if len(originals) != 1 or len(currents) != 1:
            raise ValueError("source_files")
        original, current = originals[0], currents[0]
        document = Document(
            files[original],
            original.removeprefix("original"),
            files[current],
            current.removeprefix("reviewed"),
            revision,
        )
        schema = manifest["schema"]
        if schema in {
            "fatwa.transcript-workbench.checkpoint.v1",
            "fatwa.transcript-workbench.checkpoint.v2",
        }:
            rebuilt = checkpoint(document)
        elif schema in {
            "fatwa.transcript-workbench.bundle.v1",
            "fatwa.transcript-workbench.bundle.v2",
        }:
            rebuilt = export_bundle(document)
        else:
            raise ValueError("schema")
        if files != _read_archive(rebuilt):
            raise ValueError("content_mismatch")
        return document
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("bundle: inconsistent_or_unsupported") from exc
