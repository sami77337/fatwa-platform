"""Join real FAST8 services by full origin identity, with caller-pinned revisions.

Hashes detect drift against independently retained pins, not source authenticity.
No Django setup, storage, fixed workbench lookup, media or network is used.
"""

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.fast8_segment_timeline.service import diagnose_file
from apps.fast8_transcript_queue.services import build_transcript_queue
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from tools.content_intake.cli import MAX_BYTES, parse_json

PIN_SCHEMA = "fatwa.fast9-transcript-prepared-lineage.pins.v1"
SCHEMA = "fatwa.fast9-transcript-prepared-lineage.v1"
# Reports repeat bounded source evidence across stages; inputs remain <= 1 MB.
MAX_RECEIPT_BYTES = 32 * MAX_BYTES


def _encoded(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(f"lineage: {code}")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _clock(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"


def load_pins(raw: bytes) -> dict:
    """Strict pin manifest; callers must retain it independently from input changes."""
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, "invalid_pins_size")
    try:
        pins = parse_json(raw.decode("utf-8", errors="strict"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("lineage: malformed_pins") from exc
    _require(
        isinstance(pins, dict)
        and set(pins) == {"schema", "input_sha256", "sources"}
        and pins["schema"] == PIN_SCHEMA,
        "invalid_pins_schema",
    )
    _validate_pins(pins["input_sha256"], pins["sources"])
    return pins


def _validate_pins(input_sha: str, sources: dict[str, str]) -> None:
    _require(_is_digest(input_sha), "invalid_input_pin")
    _require(
        isinstance(sources, dict)
        and 1 <= len(sources) <= 1000
        and all(isinstance(key, str) and 1 <= len(key) <= 100 for key in sources)
        and all(_is_digest(value) for value in sources.values()),
        "invalid_source_pins",
    )


@dataclass(frozen=True, slots=True)
class PreparedLineage:
    """Immutable byte snapshots. An EPHEMERAL receipt is not a scholarly draft."""

    _report: bytes
    _prepared: bytes
    _cues: bytes
    _cue_csv: bytes

    def json_bytes(self) -> bytes:
        return self._report

    def prepared_bytes(self) -> bytes:
        return self._prepared

    def cue_json_bytes(self) -> bytes:
        return self._cues

    def cue_csv_bytes(self) -> bytes:
        return self._cue_csv


def build_lineage(
    raw: bytes,
    suffix: str,
    *,
    expected_input_sha256: str,
    expected_sources: dict[str, str],
    synthetic_fixtures_only: bool = False,
) -> PreparedLineage:
    """All pairs must have answers and match exact file and complete source pins.

    File SHA covers raw bytes, including formatting CRLF. Source/segment SHA uses
    upstream canonical JSON; text SHA covers the decoded string's exact UTF-8.
    No normalization, new timing, answer preparation or draft creation occurs.
    """
    _require(synthetic_fixtures_only is True, "synthetic_fixture_acknowledgement_required")
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, "invalid_input_size")
    _validate_pins(expected_input_sha256, expected_sources)
    expected_sources = dict(expected_sources)
    input_sha = sha256(raw).hexdigest()
    _require(input_sha == expected_input_sha256, "input_pin_mismatch")

    queue = build_transcript_queue(raw, suffix, synthetic_fixtures_only=True)
    sources = {entry.source_id: entry.source_sha256 for entry in queue.entries}
    _require(sources == expected_sources, "stale_or_incomplete_source_pins")
    _require(all(entry.answer is not None for entry in queue.entries), "answer_required")
    timeline = diagnose_file(raw, suffix, synthetic_fixtures_only=True)
    timing = json.loads(timeline.json_bytes())
    cue_document = json.loads(timeline.cue_json_bytes())
    _require(
        timing["input_sha256"] == input_sha
        and cue_document["input_sha256"] == input_sha
        and timing["contract_status"] == "PASS"
        and timing["cues_allowed"] is True,
        "timeline_identity_mismatch",
    )
    _require(
        {s["source_id"]: s["source_sha256"] for s in timing["sources"]} == sources
        and len(timing["sources"]) == len(sources),
        "timeline_source_mismatch",
    )
    cues = {}
    for cue in cue_document["cues"]:
        key = (cue["source_id"], cue["segment_id"])
        _require(key not in cues, "duplicate_cue")
        cues[key] = cue

    prepared_raw = queue.prepared_bytes()
    prepared_sha = sha256(prepared_raw).hexdigest()
    prepared = prepare_batch(prepared_raw, synthetic_fixtures_only=True)
    queue_report = json.loads(queue.json_bytes())
    _require(
        prepared.report == queue_report["prepared"]
        and prepared.report["input_sha256"] == prepared_sha
        and not prepared.drafts,
        "prepared_stage_mismatch",
    )
    items = prepared.report["items"]
    _require(len(items) == len(queue.entries), "prepared_count_mismatch")
    receipts, used_cues = [], set()
    for entry, item in zip(queue.entries, items, strict=True):
        _require(
            entry.input_sha256 == input_sha
            and entry.prepared_payload_sha256 == prepared_sha
            and entry.source_sha256 == sources[entry.source_id]
            and item["original"]
            == dict(
                external_id=entry.external_id,
                question=entry.question.text,
                prepared_clip_url="",
                staff_notes="",
                reference_links=[],
            )
            and item["draft"] is None
            and not item["references"]
            and "blocked-invalid" not in item["statuses"],
            "prepared_origin_mismatch",
        )
        evidence = {}
        for segment in (entry.question, entry.answer):
            key = (entry.source_id, segment.segment_id)
            cue = cues.get(key)
            _require(cue is not None and key not in used_cues, "missing_or_reused_cue")
            _require(
                cue["source_sha256"] == entry.source_sha256
                and cue["segment_sha256"] == segment.sha256
                and cue["pair_id"] == entry.pair_id
                and cue["kind"] == segment.kind
                and cue["start_ms"] == segment.start_ms
                and cue["end_ms"] == segment.end_ms
                and cue["start_time"] == _clock(segment.start_ms)
                and cue["end_time"] == _clock(segment.end_ms)
                and cue["question_label"] == entry.question.text,
                "cue_origin_mismatch",
            )
            used_cues.add(key)
            evidence[segment.kind] = dict(
                segment=asdict(segment),
                segment_sha256=segment.sha256,
                text_utf8_sha256=sha256(segment.text.encode("utf-8")).hexdigest(),
                manual_cue=cue,
                cue_sha256=sha256(_encoded(cue)).hexdigest(),
            )
        receipt = dict(
            source_id=entry.source_id,
            source_sha256=entry.source_sha256,
            pair_id=entry.pair_id,
            external_id=entry.external_id,
            queue_key=entry.queue_key,
            input_sha256=input_sha,
            prepared_payload_sha256=prepared_sha,
            prepared_item=item,
            prepared_item_sha256=sha256(_encoded(item)).hexdigest(),
            **evidence,
        )
        receipts.append(
            dict(receipt, receipt_id="transcript-receipt-" + sha256(_encoded(receipt)).hexdigest())
        )
    _require(used_cues == set(cues), "unjoined_cue")
    report = _encoded(
        dict(
            schema=SCHEMA,
            storage="EPHEMERAL",
            origin="transcript",
            synthetic_only=True,
            mode="MANUAL",
            input_sha256=input_sha,
            input_format=suffix.lower(),
            sources=sources,
            prepared_payload_sha256=prepared_sha,
            queue_report_sha256=sha256(queue.json_bytes()).hexdigest(),
            prepared_report_sha256=sha256(prepared.json_bytes()).hexdigest(),
            timeline_report_sha256=sha256(timeline.json_bytes()).hexdigest(),
            cue_json_sha256=sha256(timeline.cue_json_bytes()).hexdigest(),
            cue_csv_sha256=sha256(timeline.cue_csv_bytes()).hexdigest(),
            receipts=receipts,
            timeline_findings=timing["findings"],
            answer_role="SOURCE_EVIDENCE_ONLY",
            answer_exported=False,
            human_editing_performed=False,
            publication_allowed=False,
            draft_count=0,
            connections=dict(
                transcript_preparation="EXACT_SYNTHETIC_JOIN",
                manual_timing="EXACT_SYNTHETIC_JOIN",
                media="NOT_CONNECTED",
                fixed_cases="NOT_CONNECTED",
                catalog="NOT_CONNECTED",
                policy="NOT_CONNECTED",
                source_owner="NOT_CONNECTED",
                production="NOT_CONNECTED",
            ),
            gates=timing["gates"],
        )
    )
    _require(len(report) <= MAX_RECEIPT_BYTES, "receipt_byte_limit")
    return PreparedLineage(
        report, prepared_raw, timeline.cue_json_bytes(), timeline.cue_csv_bytes()
    )


def verify_receipt(receipt_raw: bytes, raw: bytes, suffix: str, **kwargs) -> PreparedLineage:
    """Recompute from pinned original input; never trust an imported report's IDs."""
    _require(
        isinstance(receipt_raw, bytes) and 0 < len(receipt_raw) <= MAX_RECEIPT_BYTES,
        "invalid_receipt_size",
    )
    result = build_lineage(raw, suffix, **kwargs)
    _require(result.json_bytes() == receipt_raw, "receipt_bytes_mismatch")
    return result
