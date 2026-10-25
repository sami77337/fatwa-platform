"""Offline FAST6 bridges, preserving stock exports and reporting unresolved joins.

The consolidated report carries original packets next to explicitly transient
projections. It never replaces packet snapshots or invents persisted review data.
"""

import json
from dataclasses import asdict

from apps.editorial_export.services import (
    build_export,
    encode_json,
    require_development,
    verify_export,
)
from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_workbench.packets import build_packet
from apps.policy_gap_engine.services import build_report, canonical_json
from apps.source_readiness.pins import pinned_owner_manifest
from apps.source_readiness.service import preflight
from apps.workflow_invariants.engine import replay, scenario, snapshot
from apps.workflow_rehearsal.services import build_prepared_rehearsal, build_rehearsal

from .services import (
    MAX_REPORT_BYTES,
    JourneyError,
    JourneyReport,
    _require,
    case_identity,
    run_journey,
)


def run_integration(*, synthetic_fixtures_only: bool = False) -> JourneyReport:
    """Join fixed sources using full identity and original packet/content checks."""
    require_development(synthetic_fixtures_only)
    journey = run_journey(synthetic_fixtures_only=True)
    baseline = journey.payload()
    catalog = build_queue_catalog()
    bundle = build_export(synthetic_fixtures_only=True)
    verify_export(dict(bundle.files), synthetic_fixtures_only=True)
    batches = {batch.batch_id: batch.source for batch in catalog.batches}
    original = {row["packet"]["identity"]["case_key"]: row for row in bundle.report()["cases"]}
    expected = {row["identity"]["case_key"]: row for row in baseline["cases"]}
    keys = [row.case.key for row in catalog.rows]
    _require(
        len(keys) == len(set(keys)) and set(keys) == set(expected) == set(original),
        "integration_identity_set",
    )
    projections = []
    for row in catalog.rows:
        case = row.case
        identity = case_identity(case)
        rehearsal = (
            build_prepared_rehearsal(case.key, synthetic_fixtures_only=True)
            if hasattr(case, "batch_id")
            else build_rehearsal(case.key)
        )
        _require(
            identity == expected[case.key]["identity"] == case_identity(rehearsal.case),
            "integration_source_identity",
        )
        _require(rehearsal.source_record == case.record, "integration_source_record")
        packet = original[case.key]
        actual_packet = build_packet(case, batches[row.batch_id])
        _require(
            packet["packet_sha256"] == expected[case.key]["packet_sha256"] == actual_packet.sha256
            and packet["packet"] == actual_packet.payload(),
            "integration_packet_identity",
        )
        projected = rehearsal.projected_record
        _require(projected is None or projected.unpublished, "integration_publication")
        _require(
            case.record is not None
            or (projected is None and not any(step.accepted for step in rehearsal.steps)),
            "integration_missing_draft",
        )
        projections.append(
            {
                "identity": identity,
                "packet": packet["packet"],
                "packet_sha256": packet["packet_sha256"],
                "scope": "in_memory_projection_only",
                "projection": snapshot(projected, rehearsal.review_status),
                "steps": [asdict(step) for step in rehearsal.steps],
                "persisted": False,
                "scholarly_approval": False,
            }
        )
    permissions = json.loads(canonical_json(build_report()))
    negative = permissions["adversarial_checks"]
    _require(
        permissions["status"] == "SYNTHETIC_EVALUATED"
        and permissions["effect"] == "DENY"
        and permissions["allowed"] is False
        and permissions["active_grants"] == 0
        and bool(permissions["requests"])
        and all(
            row["effect"] == "DENY" and row["allowed"] is False for row in permissions["requests"]
        )
        and negative["status"] == "PASS"
        and negative["failed"] == 0
        and negative["evaluated"] == len(negative["checks"]) > 0
        and all(check["passed"] is True for check in negative["checks"]),
        "integration_permission_evidence",
    )
    invariants = replay(scenario())
    _require(invariants["invariants_passed"] is True, "integration_workflow_invariants")
    readiness = preflight(pinned_owner_manifest()).as_dict()
    _require(
        readiness["status"] == "BLOCKED"
        and readiness["owner_acceptance"] == "NOT_RUN"
        and readiness["observed_sha256"] == {}
        and all(check["status"] != "FAIL" for check in readiness["checks"].values()),
        "integration_source_readiness",
    )
    connections = [dict(edge) for edge in baseline["connections"]]
    for edge in connections:
        if edge["id"] == "prepared_to_rehearsal":
            edge.update(
                status="CONNECTED",
                reason="offline fixed prepared rows; exact source identity; missing drafts reject every attempt",
            )
        elif edge["id"] == "rehearsal_to_export":
            edge.update(
                status="CONNECTED",
                reason="consolidated offline report attaches transient projection to exact original packet; stock export unchanged",
            )
    return JourneyReport(
        encode_json(
            {
                "schema": "fatwa.fast6-integration.v1",
                "result": "PASS_WITH_GAPS",
                "synthetic_only": True,
                "holds": baseline["holds"],
                "execution": baseline["execution"],
                "baseline_journey_sha256": journey.sha256,
                "transcript": baseline["transcript"],
                "connections": connections,
                "projections": projections,
                "stock_export": baseline["export"],
                "workflow_invariants": invariants,
                "permission_gaps": permissions,
                "source_readiness": readiness,
                "unavailable_evidence": baseline["unavailable_evidence"],
            }
        )
    )


def verify_integration(raw: bytes, *, synthetic_fixtures_only: bool = False) -> None:
    """Verify bounded exact bytes by rerunning services, not by trusting hashes."""
    require_development(synthetic_fixtures_only)
    if type(raw) is not bytes or len(raw) > MAX_REPORT_BYTES:
        raise JourneyError("integration: invalid_report_size_or_type")
    _require(
        raw == run_integration(synthetic_fixtures_only=True).json_bytes,
        "integration_replay_mismatch",
    )
