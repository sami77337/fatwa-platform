"""Join only replay-verified source rows and initial snapshots, never review labels.

No database, clock, network, record edits or persisted review. Existing services
own every projection, packet, transition and export; this module records their
actual connections and explicitly separates the unrelated stock workflow replay.
"""

import json
from hashlib import sha256

from apps.editorial_export import services as exports
from apps.editorial_workbench import packets
from apps.fast8_packet_verifier.services import PacketVerificationError, verify_packet
from apps.fast8_prepared_review import services as prepared
from apps.fast8_review_export import services as review
from apps.workflow_invariants import engine

SCHEMA = "fatwa.fast9-prepared-review-lineage.v1"


class LineageError(ValueError):
    """Fixed content-free rejection; no partial success evidence is returned."""


def _same(left, right):
    return engine.canonical_bytes(left) == engine.canonical_bytes(right)


def _metadata(files):
    return {
        name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        for name, raw in sorted(files.items())
    }


def _status(status, reason):
    return {"status": status, "reason": reason}


def _join_packet(projection, packet):
    """Compare all documented identity fields and exact source/snapshot values.

    The parent here is the input batch, not an invented parent review event.
    Parsed row text is a serialization, never a claimed original byte slice.
    """
    identity, source = projection["source_identity"], projection["source"]
    expected_identity = {
        "case_key": identity["case_key"],
        "external_id": identity["external_id"],
        "input_sha256": identity["payload_sha256"],
        "batch_id": identity["batch_id"],
        "row_ordinal": identity["row_ordinal"],
        "source_start": source["row_start"],
        "source_end": source["row_end"],
    }
    checks = (
        _same(packet["identity"], expected_identity),
        packet["source"]["kind"] == "parsed_row_serialization",
        _same(packet["source"]["text"], source["row_text"]),
        _same(packet["source"]["input_text"], source["batch_raw_text"]),
        packet["source"]["text_sha256"] == identity["parsed_row_sha256"],
        packet["source"]["input_sha256"] == identity["payload_sha256"],
        _same(packet["reference_verification"]["results"], source["references"]),
        _same(packet["receipt"]["intake_state"], source["intake_state"]),
        _same(packet["intake_issues"], source["issues"]),
    )
    if not all(checks):
        raise LineageError("lineage: prepared_packet_identity_mismatch")
    initial = projection["initial"]
    record = initial["record"]
    if record is None:
        if packet["snapshots"] or packet["intake"]["prepared"] is not None:
            raise LineageError("lineage: absent_draft_mismatch")
        return _status("NOT_CONNECTED", "no_draft_available")
    if not (
        initial["review"] == "UNREVIEWED"
        and _same(record["history"], packet["snapshots"])
        and _same(record["intake"], packet["intake"]["prepared"])
    ):
        raise LineageError("lineage: initial_snapshot_mismatch")
    return _status("SUPPORTED", "exact_initial_intake_and_revision_snapshots")


def encode_evidence(record: dict) -> bytes:
    """Bounded canonical UTF-8 JSON with one LF; embedded text stays unchanged."""
    return exports.encode_json(record)


def build_evidence(
    request: dict,
    *,
    source_files: dict[str, bytes] | None = None,
    review_files: dict[str, bytes] | None = None,
    scenario_name: str = "rehearsal",
    synthetic_fixtures_only: bool = False,
) -> dict:
    """Return one detached deterministic record, or reject without partial evidence.

    Caller-supplied bundles must match authoritative regeneration byte for byte.
    Omitted bundles are generated in memory. Requests use the bounded FAST8
    prepared contract; arbitrary cases, actors, text or external archives cannot
    enter the fixed fixture graph. SUPPORTED means technical evidence only.
    """
    try:
        exports.require_development(synthetic_fixtures_only)
        projection = prepared.project(request)
        if source_files is None:
            source_files = dict(exports.build_export(synthetic_fixtures_only=True).files)
        elif type(source_files) is dict:
            source_files = source_files.copy()
        exports.verify_export(source_files, synthetic_fixtures_only=True)
        if review_files is None:
            review_files = dict(
                review.build_preview(
                    source_files, scenario_name=scenario_name, synthetic_fixtures_only=True
                ).files
            )
        elif type(review_files) is dict:
            review_files = review_files.copy()
        review.verify_preview(
            review_files, source_files, scenario_name=scenario_name, synthetic_fixtures_only=True
        )
        # Decode only after exact-byte verification of both complete bundles.
        report = json.loads(source_files["report.json"])
        preview = json.loads(review_files["preview.json"])
        key = projection["source_identity"]["case_key"]
        entries = [e for e in report["cases"] if e["packet"]["identity"]["case_key"] == key]
        cases = [c for c in preview["cases"] if c["case_key"] == key]
        if len(entries) != 1 or len(cases) != 1:
            raise LineageError("lineage: missing_or_ambiguous_export_member")
        packet = entries[0]["packet"]
        receipt = json.loads(
            verify_packet(
                packets.serialize_packet(packet),
                source_files["manifest.json"],
                case_key=key,
                synthetic_fixtures_only=True,
            )
        )
        snapshot_join = _join_packet(projection, packet)
        # This is the real stock engine, not a prepared request coerced into it.
        replay = engine.replay(engine.scenario(scenario_name))
        replay_digest = sha256(engine.canonical_bytes(replay)).hexdigest()
        if not (
            preview["replay"]["result_sha256"] == replay_digest
            and _same(preview["replay"]["source_identity"], replay["source_identity"])
            and cases[0]["packet_sha256"] == receipt["packet_sha256"]
            and entries[0]["packet_sha256"] == receipt["packet_sha256"]
        ):
            raise LineageError("lineage: replay_identity_mismatch")
        # Current stock replay cannot join a prepared row. Fail closed if that
        # contract changes; a new join requires explicit implementation/review.
        if (
            replay["source_identity"]["case_key"] == key
            or cases[0]["association"] != "NOT_CONNECTED"
            or cases[0]["events"]
        ):
            raise LineageError("lineage: undocumented_review_join")
        identity = projection["source_identity"]
        result = {
            "schema": SCHEMA,
            "status": "SUPPORTED",
            "meaning": "read_only_synthetic_conformance_not_end_to_end_review_acceptance",
            "synthetic_fixtures_only": True,
            "lineage_identity": {
                "case_key": key,
                "parent_batch_id": identity["batch_id"],
                "parent_payload_sha256": identity["payload_sha256"],
                "row_ordinal": identity["row_ordinal"],
                "external_id": identity["external_id"],
                "parsed_row_sha256": identity["parsed_row_sha256"],
                "prepared_case_sha256": identity["prepared_case_sha256"],
            },
            "prepared": projection,
            "attempts": [
                {
                    "ordinal": step["ordinal"],
                    "status": "SUPPORTED" if step["accepted"] else step["disposition"],
                    "reason": step["reason"],
                }
                for step in projection["steps"]
            ],
            "packet": packet,
            "packet_verification": receipt,
            "source_members": _metadata(source_files),
            "review_members": _metadata(review_files),
            "review_export_case": cases[0],
            "workflow_replay": preview["replay"],
            "joins": {
                "prepared_to_packet": _status(
                    "SUPPORTED", "exact_parent_source_row_and_references"
                ),
                "initial_snapshot_to_export": snapshot_join,
                "prepared_to_workflow_replay": _status(
                    "NOT_CONNECTED", "stock_case_is_not_prepared_case"
                ),
                "projected_review_to_export": _status(
                    "NOT_CONNECTED", "no_prepared_review_export_contract"
                ),
                "persisted_review": _status("NOT_CONNECTED", "no_persisted_review_loaded_or_bound"),
            },
            "execution": {
                "postgresql": _status("NOT_RUN", "offline_contracts_only_no_database_access"),
                "browser": _status("NOT_RUN", "no_ui_or_http_surface"),
            },
            "gates": projection["gates"],
            "acceptance": {
                name: "NOT_CONNECTED"
                for name in ("source_owner", "catalog", "policy", "production")
            },
        }
        return json.loads(encode_evidence(result))
    except (
        exports.ExportError,
        prepared.BridgeError,
        PacketVerificationError,
        packets.PacketDataError,
        engine.ReplayError,
    ) as exc:
        # All called contracts have stable codes; do not echo arbitrary input.
        raise LineageError("lineage: contract_verification_rejected") from exc
