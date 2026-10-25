"""Replay existing FAST5 services without persistence, network or invented joins.

This is an integration verifier, not a new intake/workflow authority. Every join
uses the complete available source identity; external IDs alone are insufficient.
"""

import base64
import csv
import io
import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from apps.editorial_export.services import (
    HOLDS,
    build_export,
    encode_json,
    require_development,
    verify_export,
)
from apps.editorial_queue.services import build_queue_catalog, select_queue
from apps.editorial_workbench.batch_fixtures import synthetic_inputs
from apps.editorial_workbench.packets import build_packet, serialize_packet
from apps.editorial_workbench.services import WorkbenchCase, _asserted_catalog
from apps.fatwa_drafts.intake import ValidationError
from apps.permission_lab.services import build_catalog, evaluate
from apps.prepared_pipeline import prepare_batch
from apps.prepared_pipeline.diagnostics import diagnose_batches
from apps.reference_links.resolution import SnapshotCatalog
from apps.reference_triage.services import ReferenceTriage, build_investigation
from apps.research_bridge.services import bridge_reference
from apps.revision_core.revision_history import (
    InvalidRevisionId,
    UnknownRevisionId,
    navigate_history,
    select_revisions,
)
from apps.transcript_pipeline import segment_file
from apps.workflow_rehearsal.services import CASE_KEYS, build_rehearsal

BASE_COMMIT = "0eef6b29943364dddae35a193b356ab79a2e2b5e"
TRANSCRIPT_PATH = "tools/transcript_pipeline/examples/synthetic-manual.json"
MAX_REPORT_BYTES = 2_000_000


class JourneyError(ValueError):
    """A connected-stage invariant failed; never emit a passing report."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise JourneyError("journey: " + code)


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class JourneyReport:
    json_bytes: bytes

    @property
    def sha256(self) -> str:
        return _digest(self.json_bytes)

    def payload(self) -> dict:
        return json.loads(self.json_bytes)


def case_identity(case: WorkbenchCase) -> dict:
    """All available source pins, including ordinal/slice and exact source hash."""
    return {
        "case_key": case.key,
        "external_id": case.external_id,
        "input_sha256": case.payload_sha256,
        "source_sha256": _digest(case.raw_source.encode("utf-8")),
        "batch_id": getattr(case, "batch_id", None),
        "row_ordinal": getattr(case, "row_ordinal", None),
        "source_start": case.source_start,
        "source_end": case.source_end,
    }


def _transcript() -> dict:
    # A single named repository fixture, not caller-selected source discovery.
    raw = (Path(__file__).resolve().parents[2] / TRANSCRIPT_PATH).read_bytes()
    original = json.loads(raw)
    transcript = segment_file(raw, ".json", synthetic_fixtures_only=True)
    report = json.loads(transcript.json_bytes())
    exported = transcript.prepared_bytes()
    items = json.loads(exported)["items"]
    prepared = prepare_batch(exported, synthetic_fixtures_only=True)
    _require(report["segments"] == original["items"], "transcript_unicode_or_timestamps")
    _require(report["input_sha256"] == _digest(raw), "transcript_input_hash")
    _require(prepared.report["input_sha256"] == _digest(exported), "prepared_input_hash")
    traces = []
    for pair, item, receipt in zip(report["pairs"], items, prepared.report["items"], strict=True):
        question = next(
            segment
            for segment in report["segments"]
            if (segment["source_id"], segment["segment_id"])
            == (pair["source_id"], pair["question_segment_id"])
        )
        _require(pair["external_id"] == item["external_id"], "transcript_pair_identity")
        _require(
            receipt["original"] == item and item["question"] == question["text"],
            "transcript_prepared_identity",
        )
        _require(
            receipt["draft"] is None
            and receipt["statuses"] == ["needs-editor-review", "references-unverified"],
            "transcript_missing_inputs",
        )
        traces.append(
            {
                **pair,
                "prepared_row": receipt["row"],
                "question": item["question"],
                "findings": receipt["findings"],
            }
        )
    _require(not prepared.drafts, "transcript_unexpected_draft")
    invalid = json.loads(raw)
    invalid["items"][0]["end_ms"] = invalid["items"][0]["start_ms"]
    try:
        segment_file(encode_json(invalid), ".json", synthetic_fixtures_only=True)
    except ValidationError:
        pass
    else:
        raise JourneyError("journey: invalid_timestamp_accepted")
    return {
        "fixture_path": TRANSCRIPT_PATH,
        "input_sha256": _digest(raw),
        "report_sha256": _digest(transcript.json_bytes()),
        "prepared_output_sha256": _digest(exported),
        "prepared_input_sha256": prepared.report["input_sha256"],
        "receipt_sha256": _digest(prepared.json_bytes()),
        "segments": report["segments"],
        "pairs": traces,
        "draft_count": len(prepared.drafts),
        "invalid_timestamp": "REJECTED",
        "answer_exported": False,
    }


def _diagnostics(cases: tuple[WorkbenchCase, ...]) -> dict:
    inputs = synthetic_inputs()
    result = diagnose_batches(inputs, synthetic_fixtures_only=True)
    report = result.report
    sources = {item.batch_id: item for item in inputs}
    rows = {(row["batch_id"], row["row"]): row for row in report["rows"]}
    for case in cases:
        if not hasattr(case, "batch_id"):
            continue
        row = rows[(case.batch_id, case.row_ordinal)]
        provenance = row["provenance"]
        source = sources[case.batch_id]
        _require(
            case.payload_sha256 == provenance["input_sha256"] == _digest(source.raw),
            "diagnostic_source_identity",
        )
        _require(row["preparation"]["original"] == case.original, "diagnostic_row_identity")
        _require(
            base64.b64decode(provenance["raw_base64"], validate=True)
            == source.raw[provenance["byte_start"] : provenance["byte_end"]],
            "diagnostic_source_slice",
        )
        # Diagnostics intentionally have no trusted reference map. Join original
        # data only; never substitute their reference decisions for workbench's.
        if "blocked-invalid" in row["preparation"]["statuses"]:
            _require(case.record is None, "rejected_row_has_draft")
    return {
        "report_sha256": _digest(result.json_bytes()),
        "source_inventory": report["inventory"],
        "summary": report["summary"],
        "inputs": [
            {k: v for k, v in item.items() if k != "raw_base64"} for item in report["inputs"]
        ],
        "duplicate_groups": report["duplicate_groups"],
        "malformed_batches": [
            item["batch_id"] for item in report["inputs"] if item["error_code"] == "MALFORMED_INPUT"
        ],
        "rows": [
            {
                "batch_id": row["batch_id"],
                "row_id": row["row_id"],
                "row": row["row"],
                "diagnostics": row["diagnostics"],
            }
            for row in report["rows"]
        ],
    }


def _authorization() -> dict:
    catalog = build_catalog()
    triples = [(actor, "synthetic::answer.create", "synthetic::answer") for actor in catalog.actors]
    triples += [
        ("MUFTI", "complete_review", "workflow::IN_REVIEW"),
        ("DOMAIN_TRANSACTION", "synthetic::answer.create", "synthetic::answer"),
        ("MUFTI", "publish", "synthetic::answer"),
        ("MUFTI ", "synthetic::answer.create", "synthetic::answer"),
    ]
    decisions = []
    for actor, action, resource in triples:
        decision = evaluate(actor, action, resource)
        _require(decision.effect == "DENY" and decision.allowed is False, "authorization_grant")
        decisions.append(
            {"actor": actor, "action": action, "resource": resource, **asdict(decision)}
        )
    return {
        "source_commit": catalog.source_commit,
        "inventory_sha256": catalog.inventory_sha256,
        "decisions": decisions,
        "case_binding": "NOT_CONNECTED",
    }


def _rehearsal(case: WorkbenchCase) -> dict:
    if case.key not in CASE_KEYS:
        return {"status": "NOT_CONNECTED", "reason": "selector_has_no_prepared_case_adapter"}
    rehearsal = build_rehearsal(case.key)
    _require(case_identity(rehearsal.case) == case_identity(case), "rehearsal_identity")
    _require(rehearsal.source_record == case.record, "rehearsal_source_revision")
    if rehearsal.projected_record is not None:
        _require(rehearsal.projected_record.unpublished, "rehearsal_publication")
    _require(
        all(not step.accepted for step in rehearsal.steps if step.action == "published"),
        "rehearsal_publication_accepted",
    )
    if case.record is None:
        _require(not any(step.accepted for step in rehearsal.steps), "rehearsal_without_draft")
    return {
        "status": "CONNECTED",
        "scope": "in_memory_projection_only",
        "source_record_sha256": _digest(serialize_packet(asdict(case.record)))
        if case.record
        else None,
        "projected_record_sha256": _digest(serialize_packet(asdict(rehearsal.projected_record)))
        if rehearsal.projected_record
        else None,
        "steps": [asdict(step) for step in rehearsal.steps],
        "review_label": rehearsal.review_status,
        "persisted": False,
        "scholarly_approval": False,
    }


def _csv_rows(raw: bytes) -> list[dict]:
    return [
        {key: json.loads(value) for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""))
    ]


def _verify_occurrences(case: WorkbenchCase, references: tuple[ReferenceTriage, ...]) -> None:
    """Bind derived investigation evidence to each original case occurrence."""
    _require(len(references) == len(case.references), "reference_occurrence_count")
    for ordinal, (ref, raw) in enumerate(zip(references, case.references, strict=True), 1):
        source = raw["source"]
        _require(
            ref.ordinal == raw["reference_ordinal"] == ordinal
            and ref.raw_status == raw["status"]
            and (ref.status == "verified") == (raw["status"] == "verified")
            and ref.contract_status == raw["contract_status"]
            and ref.reasons == tuple(raw["reasons"])
            and ref.source_text == source["text"]
            and ref.source_start == source["start"]
            and ref.source_end == source["end"]
            and ref.source_sha256 == _digest(source["text"].encode("utf-8"))
            and json.loads(ref.original_identity) == raw.get("original_identity", {})
            and json.loads(ref.verified_identity) == raw["verified_identity"]
            # JSON represents existing tuple paths as arrays; no text normalization.
            and json.loads(ref.evidence) == json.loads(encode_json(raw["evidence"])),
            "reference_occurrence_identity_or_evidence",
        )


def run_journey(*, synthetic_fixtures_only: bool = False) -> JourneyReport:
    """Assert real stage connections, report explicit gaps, return immutable evidence.

    Raises on any mismatch. There is no input path, catalog override, clock, git
    process, DB fallback, media fetch, write endpoint or persistent transition.
    """
    require_development(synthetic_fixtures_only)
    transcript = _transcript()
    queue = build_queue_catalog()
    investigation = build_investigation()
    queue_keys = [row.case.key for row in queue.rows]
    triage_keys = [row.case.key for row in investigation.cases]
    _require(
        len(queue_keys) == len(set(queue_keys)) and queue_keys == triage_keys,
        "queue_triage_identity_set",
    )
    bundle = build_export(synthetic_fixtures_only=True)
    verify_export(dict(bundle.files), synthetic_fixtures_only=True)
    exported = bundle.report()
    _require(_csv_rows(bundle.file("cases.csv")) == exported["cases"], "csv_case_roundtrip")
    _require(_csv_rows(bundle.file("batches.csv")) == exported["batches"], "csv_batch_roundtrip")
    exported_keys = [entry["packet"]["identity"]["case_key"] for entry in exported["cases"]]
    _require(sorted(queue_keys) == exported_keys, "export_identity_set")
    entries = dict(zip(exported_keys, exported["cases"], strict=True))
    batches = {batch.batch_id: batch.source for batch in queue.batches}
    catalog = SnapshotCatalog(_asserted_catalog())
    cases = []
    for index, (row, triage) in enumerate(zip(queue.rows, investigation.cases, strict=True)):
        case = row.case
        identity = case_identity(case)
        _require(identity == case_identity(triage.case), "triage_source_identity")
        _require(case == triage.case, "triage_content_identity")
        _require(
            row.source_sha256 == triage.source_sha256 == identity["source_sha256"],
            "source_digest_identity",
        )
        selection = select_queue(queue.rows, key=case.key)
        _require(
            selection.selected is row and selection.position == index + 1,
            "queue_navigation_identity",
        )
        previous = queue.rows[index - 1] if index else None
        following = queue.rows[index + 1] if index + 1 < len(queue.rows) else None
        _require(selection.previous is previous and selection.next is following, "queue_neighbors")
        packet = build_packet(case, batches[row.batch_id])
        payload = packet.payload()
        entry = entries[case.key]
        _require(
            entry["packet"] == payload and entry["packet_sha256"] == packet.sha256,
            "export_packet_identity",
        )
        _require(
            payload["scholarly_decision"] is None and payload["review_conclusion"] is None,
            "unexpected_scholarly_decision",
        )
        _require(payload["holds"] == list(HOLDS), "packet_holds")
        numbers = [history.revision.number for history in row.history]
        for history in row.history:
            navigation = navigate_history(case.record, str(history.revision.number))
            _require(navigation.selected is history.revision, "revision_object_identity")
        if row.history:
            for invalid in ("01", "١", "999999"):
                try:
                    select_revisions(row.history, invalid, invalid)
                except (InvalidRevisionId, UnknownRevisionId):
                    pass
                else:
                    raise JourneyError("journey: invalid_revision_accepted")
        _verify_occurrences(case, triage.references)
        references = []
        for ref in triage.references:
            result = bridge_reference(ref, catalog)
            empty = bridge_reference(ref, SnapshotCatalog(()))
            _require(
                empty.catalog_url is None and empty.status == "unverified",
                "missing_catalog_link_open",
            )
            if result.status != "verified":
                _require(result.catalog_url is None, "unverified_catalog_link_open")
            references.append(
                {
                    "ordinal": ref.ordinal,
                    "source_sha256": ref.source_sha256,
                    "original_identity": json.loads(ref.original_identity),
                    "status": result.status,
                    "reason": result.reason,
                    "catalog_url": result.catalog_url,
                    "empty_catalog_url": empty.catalog_url,
                    "empty_catalog_reason": empty.reason,
                    "evidence": asdict(result.evidence) if result.evidence else None,
                }
            )
        cases.append(
            {
                "identity": identity,
                "question": case.question,
                "receipt_status": case.status,
                "issues": list(case.issues),
                "revision_numbers": numbers,
                "revision_snapshots_sha256": _digest(encode_json(payload["snapshots"])),
                "packet_sha256": packet.sha256,
                "references": references,
                "queue": {
                    "position": selection.position,
                    "previous": previous.case.key if previous else None,
                    "next": following.case.key if following else None,
                },
                "packet_path": entry["navigation"]["packet_path"],
                "rehearsal": _rehearsal(case),
                "persisted_review": payload["persisted_review"]["status"],
                "scholarly_decision": payload["scholarly_decision"],
            }
        )
    unknown = select_queue(queue.rows, key="not-a-fixture")
    _require(unknown.selected is None and unknown.position is None, "unknown_queue_fallback")
    return JourneyReport(
        encode_json(
            {
                "schema": "fatwa.fast6-journey.v1",
                "baseline_commit": BASE_COMMIT,
                "result": "PASS_WITH_GAPS",
                "synthetic_only": True,
                "holds": HOLDS,
                "execution": {
                    "services": "PASS",
                    "http": "NOT_RUN",
                    "browser": "NOT_RUN",
                    "postgres": "NOT_RUN",
                    "owner_archives": "NOT_RUN",
                    "catalog": "fixed_synthetic_snapshot",
                    "writes": False,
                    "network_requests": False,
                },
                "transcript": transcript,
                "cases": cases,
                "diagnostics": _diagnostics(tuple(row.case for row in queue.rows)),
                "authorization": _authorization(),
                "export": {
                    "verification": "exact_byte_replay",
                    "files": {
                        name: {"sha256": _digest(raw), "bytes": len(raw)}
                        for name, raw in bundle.files
                    },
                },
                "connections": [
                    {
                        "id": "transcript_to_stock_queue",
                        "status": "NOT_CONNECTED",
                        "reason": "prepared transcript lacks media/references; stock queue loads independent fixed fixtures",
                    },
                    {
                        "id": "prepared_to_rehearsal",
                        "status": "NOT_CONNECTED",
                        "reason": "rehearsal selector accepts original cases only",
                    },
                    {
                        "id": "rehearsal_to_export",
                        "status": "NOT_CONNECTED",
                        "reason": "export contains original snapshots, never projected review events",
                    },
                    {
                        "id": "permission_to_case",
                        "status": "NOT_CONNECTED",
                        "reason": "permission resources are hypothetical labels, not case bindings",
                    },
                    {"id": "transcript_to_prepared", "status": "CONNECTED"},
                    {"id": "queue_to_triage_packet_export", "status": "CONNECTED"},
                    {"id": "original_to_rehearsal", "status": "CONNECTED"},
                ],
                "unavailable_evidence": [
                    "owner source archives",
                    "historical 70 permission rows",
                    "historical 58 transitions",
                    "U03/U10 owner acceptance",
                    "persisted review linkage",
                    "live PostgreSQL catalog",
                ],
            }
        )
    )


def verify_journey(raw: bytes, *, synthetic_fixtures_only: bool = False) -> None:
    """Bound before parsing; replay exact bytes instead of trusting reported hashes."""
    require_development(synthetic_fixtures_only)
    if type(raw) is not bytes or len(raw) > MAX_REPORT_BYTES:
        raise JourneyError("journey: invalid_report_size_or_type")
    _require(raw == run_journey(synthetic_fixtures_only=True).json_bytes, "replay_mismatch")
