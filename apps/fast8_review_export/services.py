"""Additive evidence over verified immutable exports and fixed workflow replay.

Existing services own the packets, transitions, hashes and serializers. This
adapter only associates their evidence. It accepts no records, actors, commands,
timestamps, database connections or purportedly verified workflow results.
"""

import json
from hashlib import sha256

from apps.editorial_export import services as exports
from apps.workflow_invariants import engine

SCENARIOS = ("rehearsal", "preparation", "blocked")
FILE_NAMES = ("preview.json", "review-events.csv", "manifest.json")
EVENT_COLUMNS = (
    "case_key",
    "ordinal",
    "event",
    "event_sha256",
    "accepted",
    "disposition",
    "reason",
    "original_ordinal",
    "before",
    "after",
    "before_sha256",
    "after_sha256",
    "state_changed",
    "changed_paths",
)
HOLDS = (*exports.HOLDS, "U03/U10 OWNER_APPROVAL_PENDING")


def _same(left: object, right: object) -> bool:
    # JSON bytes distinguish bool/int aliases and retain exact Arabic/CRLF.
    return exports.encode_json(left) == exports.encode_json(right)


def _metadata(files: dict[str, bytes]) -> dict:
    return {
        name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        for name, raw in sorted(files.items())
    }


def _project_case(entry: dict, result: dict) -> dict:
    """Internal association only; callers must use the replay-verified API below.

    Missing or mismatching associations never fall back to external_id or a
    similar snapshot. Workflow state hashes are distinct from packet hashes.
    """
    packet = entry["packet"]
    identity = packet["identity"]
    projected = {
        "case_key": identity["case_key"],
        "packet_sha256": entry["packet_sha256"],
        "association": "NOT_CONNECTED",
        "snapshot": "UNAVAILABLE",
        "reason": "no_replay_for_exact_case_key",
        "source": None,
        "events": [],
    }
    replay_identity = result.get("source_identity")
    if not isinstance(replay_identity, dict) or not _same(
        identity["case_key"], replay_identity.get("case_key")
    ):
        return projected
    if (
        packet.get("schema") != "synthetic-case-review-packet.v1"
        or packet.get("synthetic_only") is not True
        or result.get("schema") != engine.SCHEMA + ".result"
        or result.get("synthetic_fixtures_only") is not True
    ):
        projected["reason"] = "unavailable_contract"
        return projected
    source = packet.get("source")
    references = packet.get("reference_verification", {}).get("results")
    if not isinstance(source, dict) or not isinstance(references, list):
        projected["reason"] = "missing_source_identity"
        return projected
    mapped_identity = {
        "case_key": identity["case_key"],
        "external_id": identity.get("external_id"),
        "payload_sha256": identity.get("input_sha256"),
        "source_sha256": source.get("text_sha256"),
        "source_start": identity.get("source_start"),
        "source_end": identity.get("source_end"),
        "reference_identities": [
            {field: ref.get(field) for field in ("source", "source_sha256", "verified_identity")}
            for ref in references
        ],
    }
    replay_source = result.get("source", {})
    if (
        identity.get("batch_id") is not None
        or identity.get("row_ordinal") is not None
        or not _same(mapped_identity, replay_identity)
        or not _same(source.get("text"), replay_source.get("raw_text"))
        or not _same(references, replay_source.get("references"))
        or not _same(source.get("start"), replay_source.get("start"))
        or not _same(source.get("end"), replay_source.get("end"))
    ):
        projected["reason"] = "source_identity_mismatch"
        return projected
    projected["association"] = "CONNECTED"
    initial = result.get("initial")
    record = initial.get("record") if isinstance(initial, dict) else None
    if (
        not isinstance(record, dict)
        or not record.get("history")
        or not packet.get("snapshots")
        or packet.get("intake", {}).get("prepared") is None
    ):
        projected["reason"] = "missing_snapshot"
        return projected
    if (
        not _same(record.get("history"), packet["snapshots"])
        or not _same(record.get("intake"), packet["intake"]["prepared"])
        or initial.get("review") != "UNREVIEWED"
    ):
        projected.update(association="NOT_CONNECTED", reason="snapshot_mismatch")
        return projected
    projected.update(
        snapshot="AVAILABLE",
        reason="exact_source_and_initial_snapshot",
        source=source,
        events=[
            {"case_key": identity["case_key"], **step}
            for step in result["steps"]
            if step["event"].get("dimension") == "review"
        ],
    )
    return projected


def build_preview(
    source_files: dict[str, bytes],
    *,
    scenario_name: str = "rehearsal",
    synthetic_fixtures_only: bool = False,
) -> exports.ExportBundle:
    """Verify the original four files, then replay a code-selected scenario.

    Preview is a separate three-file bundle, never a replacement export. Only
    fixed synthetic scenarios are accepted; persisted review is NOT_CONNECTED.
    """
    exports.require_development(synthetic_fixtures_only)
    if type(scenario_name) is not str or scenario_name not in SCENARIOS:
        raise exports.ExportError("review_preview: unknown_fixed_scenario")
    if type(source_files) is not dict:
        raise exports.ExportError("review_preview: unexpected_source_files")
    source_files = source_files.copy()
    exports.verify_export(source_files, synthetic_fixtures_only=True)
    # Parsing happens only after authoritative byte replay, including manifest.
    report = json.loads(source_files["report.json"])
    request = engine.scenario(scenario_name)
    result = engine.replay(request)
    cases = [_project_case(entry, result) for entry in report["cases"]]
    events = [event for case in cases for event in case["events"]]
    provenance = {
        "scenario": scenario_name,
        "schema": result["schema"],
        "contract_version": result["contract_version"],
        "source_identity": result["source_identity"],
        "request_sha256": result["input_sha256"],
        "result_sha256": sha256(engine.canonical_bytes(result)).hexdigest(),
        "hash_encoding": "workflow_invariants canonical UTF-8 JSON without trailing newline",
        "owner_transitions": result["owner_transitions"],
    }
    preview = {
        "schema": "synthetic-review-export-preview.v1",
        "synthetic_only": True,
        "scope": "offline_internal_review_evidence_only",
        "holds": HOLDS,
        "persisted_review": "NOT_CONNECTED",
        "scholarly_decision": None,
        "review_conclusion": None,
        "source_files": _metadata(source_files),
        "replay": provenance,
        "cases": cases,
        "counts": {
            "cases": len(cases),
            "projected_review_attempts": len(events),
            "omitted_review_attempts": sum(
                step["event"]["dimension"] == "review" for step in result["steps"]
            )
            - len(events),
            "excluded_preparation_attempts": sum(
                step["event"]["dimension"] == "preparation" for step in result["steps"]
            ),
        },
        "interpretation": (
            "APPLIED/REPLAY/REJECTED and REVIEWED_INTERNAL are synthetic technical evidence; "
            "accepted retries are not new applied events. No human or scholarly completion. "
            "Before/after hashes cover workflow record+review states, not packet bytes. "
            "Preparation attempts are excluded from rows but remain in authoritative replay; "
            "event ordinals and before/after snapshots preserve their effects."
        ),
        "csv_encoding": "UTF-8 without BOM; RFC4180 CRLF; each data cell is canonical JSON",
    }
    files = (
        ("preview.json", exports.encode_json(preview)),
        ("review-events.csv", exports.encode_csv(EVENT_COLUMNS, events)),
    )
    manifest = {
        "schema": "synthetic-review-export-preview-manifest.v1",
        "synthetic_only": True,
        "holds": HOLDS,
        "files": _metadata(dict(files)),
        "source_files": _metadata(source_files),
        "replay": provenance,
        "verification": (
            "Exact-byte regeneration from verified fixed synthetic export and selected scenario; "
            "digests are integrity checks, not signatures or scholarly approval."
        ),
    }
    files += (("manifest.json", exports.encode_json(manifest)),)
    if sum(len(raw) for _, raw in files) > exports.MAX_BUNDLE_BYTES:
        raise exports.ExportError("review_preview: bundle_byte_limit")
    return exports.ExportBundle(files)


def verify_preview(
    files: dict[str, bytes],
    source_files: dict[str, bytes],
    *,
    scenario_name: str = "rehearsal",
    synthetic_fixtures_only: bool = False,
) -> None:
    """Do not deserialize an untrusted preview, even its rehashed manifest."""
    exports.require_development(synthetic_fixtures_only)
    if type(files) is not dict or set(files) != set(FILE_NAMES):
        raise exports.ExportError("review_preview: unexpected_files")
    files = files.copy()
    if any(type(raw) is not bytes or len(raw) > exports.MAX_FILE_BYTES for raw in files.values()):
        raise exports.ExportError("review_preview: invalid_file_size_or_type")
    if sum(map(len, files.values())) > exports.MAX_BUNDLE_BYTES:
        raise exports.ExportError("review_preview: bundle_byte_limit")
    expected = build_preview(
        source_files, scenario_name=scenario_name, synthetic_fixtures_only=True
    )
    if files != dict(expected.files):
        raise exports.ExportError("review_preview: replay_mismatch")
