"""Consumer-pinned scenarios over existing FAST6 services, never external-ID joins."""

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from apps.editorial_export.services import encode_json, require_development
from apps.editorial_workbench.services import _asserted_catalog
from apps.fast6_journey.integration import run_integration
from apps.fast6_journey.services import JourneyReport, _verify_occurrences, case_identity
from apps.reference_links.resolution import SnapshotCatalog
from apps.reference_triage.services import build_investigation
from apps.research_bridge.services import bridge_reference

BASE_SHA = "92fa517ecdefe3f1a92a1ab145ff55943474df44"
MAX_CONTRACT_BYTES = 65536
SCHEMA = "fatwa.fast8-scenarios.v1"
STAGES = frozenset(
    {
        "transcript",
        "prepared_receipt",
        "queue_triage_packet",
        "review_projection",
        "stock_export",
        "research",
        "persisted_review",
        "permission_case_binding",
    }
)


class ConformanceError(ValueError):
    """No passing report may be emitted for invalid or stale evidence."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ConformanceError("conformance: " + code)


def _exact(left: object, right: object) -> bool:
    # Canonical JSON distinguishes bool/int and null/missing; no normalization.
    return encode_json(left) == encode_json(right)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def default_contract() -> bytes:
    """Committed consumer pins, not regenerated from the observed run."""
    return Path(__file__).with_name("scenarios.json").read_bytes()


def parse_contract(raw: bytes) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_CONTRACT_BYTES, "contract_size")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        _require(type(data) is dict, "contract_shape")
        _require(set(data) == {"schema", "baseline_sha", "scenarios"}, "contract_fields")
        _require(data["schema"] == SCHEMA and data["baseline_sha"] == BASE_SHA, "contract_base")
        rows = data["scenarios"]
        _require(type(rows) is list and 0 < len(rows) <= 32, "scenario_count")
        seen = set()
        for row in rows:
            _require(type(row) is dict, "scenario_shape")
            _require(
                set(row) == {"id", "kind", "anchor", "required", "extensions"}, "scenario_fields"
            )
            name = row["id"]
            _require(
                type(name) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) is not None,
                "scenario_id",
            )
            _require(name not in seen, "duplicate_scenario")
            seen.add(name)
            _require(row["kind"] in ("case", "transcript"), "scenario_kind")
            _require(type(row["anchor"]) is dict, "missing_anchor")
            for field in ("required", "extensions"):
                values = row[field]
                _require(type(values) is list and len(values) <= 16, "stage_list")
                _require(all(type(v) is str for v in values), "stage_name")
                _require(len(values) == len(set(values)), "duplicate_stage")
            _require(bool(row["required"]) and set(row["required"]) <= STAGES, "required_stage")
            _require(
                all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", v) for v in row["extensions"]),
                "extension_name",
            )
        # Also reject nonfinite numbers, oversized integers and malformed strings.
        encode_json(data)
    except (UnicodeError, RecursionError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ConformanceError("conformance: invalid_contract") from exc
    return data


@dataclass(frozen=True, slots=True)
class ScenarioAnchor:
    """Immutable exact source identity plus original packet pin for a sibling probe."""

    json_bytes: bytes


@dataclass(frozen=True, slots=True)
class AdapterEvidence:
    anchor: ScenarioAnchor
    status: str


class BoundaryProbe(Protocol):
    def __call__(self, anchor: ScenarioAnchor) -> AdapterEvidence:
        """Run a trusted read-only adapter check; never authorize product actions."""
        ...


def _stage(status: str, reason: str, **evidence) -> dict:
    return {"status": status, "reason": reason, **evidence}


def _research(identity: dict, investigation) -> dict:
    matches = [row for row in investigation.cases if row.case.key == identity["case_key"]]
    _require(len(matches) == 1, "research_identity_missing_or_ambiguous")
    row = matches[0]
    _require(_exact(case_identity(row.case), identity), "research_identity_stale")
    _verify_occurrences(row.case, row.references)
    catalog = SnapshotCatalog(_asserted_catalog())
    references = []
    for ref in row.references:
        result = bridge_reference(ref, catalog)
        empty = bridge_reference(ref, SnapshotCatalog(()))
        _require(empty.catalog_url is None and empty.status == "unverified", "empty_catalog_open")
        _require(result.status == "verified" or result.catalog_url is None, "unverified_link_open")
        references.append(
            {
                "ordinal": ref.ordinal,
                "source_sha256": ref.source_sha256,
                "status": result.status,
                "catalog_url": result.catalog_url,
                "empty_catalog_status": empty.status,
                "empty_catalog_url": empty.catalog_url,
            }
        )
    return _stage("PASS", "fixed_synthetic_catalog_only", references=references)


def run_conformance(
    contract: bytes | None = None,
    *,
    scenario: str | None = None,
    synthetic_fixtures_only: bool = False,
    probes: dict[str, BoundaryProbe] | None = None,
) -> JourneyReport:
    """Validate consumer pins before probes; unavailable required stages fail closed.

    PASS describes a technical boundary assertion, never scholarly acceptance.
    Optional probes are code-injected, not imported from CLI/contract values. Their
    result only covers their own identity check; core stage gaps remain unchanged.
    """
    require_development(synthetic_fixtures_only)
    raw = default_contract() if contract is None else contract
    request = parse_contract(raw)
    rows = request["scenarios"]
    if scenario is not None:
        _require(type(scenario) is str, "unknown_scenario")
        rows = [row for row in rows if row["id"] == scenario]
        _require(len(rows) == 1, "unknown_scenario")
    integration = run_integration(synthetic_fixtures_only=True)
    observed = integration.payload()
    projections = observed["projections"]
    keys = [row["identity"]["case_key"] for row in projections]
    _require(len(keys) == len(set(keys)), "ambiguous_case_identity")
    by_key = dict(zip(keys, projections, strict=True))
    selected = []
    # Validate every requested identity before any extension can execute.
    for row in rows:
        if row["kind"] == "case":
            anchor = row["anchor"]
            _require(set(anchor) == {"identity", "packet_sha256"}, "case_anchor_fields")
            identity = anchor["identity"]
            _require(
                type(identity) is dict and type(identity.get("case_key")) is str, "missing_identity"
            )
            current = by_key.get(identity["case_key"])
            _require(current is not None, "missing_case")
            expected = {"identity": current["identity"], "packet_sha256": current["packet_sha256"]}
        else:
            current = None
            expected = {
                key: observed["transcript"][key]
                for key in ("fixture_path", "input_sha256", "prepared_output_sha256")
            }
        _require(_exact(row["anchor"], expected), "stale_or_incomplete_anchor")
        selected.append((row, current))
    investigation = build_investigation() if any(p is not None for _, p in selected) else None
    results = []
    for row, projection in selected:
        stages = {
            name: _stage("NOT_CONNECTED", "no_same_identity_adapter") for name in sorted(STAGES)
        }
        if projection is None:
            stages["transcript"] = _stage(
                "PASS",
                "existing_segmenter_exact_text_and_timestamps",
                evidence=observed["transcript"],
            )
            stages["prepared_receipt"] = _stage(
                "PASS", "receipt_only_no_draft", draft_count=observed["transcript"]["draft_count"]
            )
        else:
            packet = projection["packet"]
            _require(
                projection["persisted"] is False and projection["scholarly_approval"] is False,
                "projection_authority",
            )
            _require(
                packet["scholarly_decision"] is None and packet["review_conclusion"] is None,
                "packet_authority",
            )
            _require(packet["persisted_review"]["status"] == "not_loaded", "persisted_review_claim")
            stages["queue_triage_packet"] = _stage(
                "PASS",
                "fast6_exact_identity_and_original_packet",
                packet_sha256=projection["packet_sha256"],
            )
            stages["stock_export"] = _stage(
                "PASS",
                "original_snapshots_only",
                packet_sha256=projection["packet_sha256"],
                files=observed["stock_export"]["files"],
            )
            stages["review_projection"] = _stage(
                "PASS",
                "in_memory_projection_only",
                projection=projection["projection"],
                steps=projection["steps"],
                persisted=False,
                scholarly_approval=False,
            )
            stages["research"] = _research(projection["identity"], investigation)
            if projection["identity"]["batch_id"] is not None:
                stages["prepared_receipt"] = _stage(
                    "PASS",
                    "existing_prepared_row_not_transcript",
                    draft_present=bool(packet["snapshots"]),
                )
        stages["persisted_review"] = _stage(
            "NOT_CONNECTED", "original_export_has_no_persisted_review"
        )
        stages["permission_case_binding"] = _stage(
            "NOT_CONNECTED", "hypothetical_permission_resources_not_case_bindings"
        )
        extensions = []
        for name in row["extensions"]:
            probe = (probes or {}).get(name)
            if probe is None:
                extensions.append({"id": name, "status": "NOT_CONNECTED", "execution": "NOT_RUN"})
                continue
            anchor = ScenarioAnchor(encode_json(row["anchor"]))
            evidence = probe(anchor)
            _require(type(evidence) is AdapterEvidence, "extension_evidence_type")
            _require(
                type(evidence.anchor) is ScenarioAnchor
                and type(evidence.anchor.json_bytes) is bytes
                and evidence.anchor.json_bytes == anchor.json_bytes,
                "extension_stale_identity",
            )
            _require(
                type(evidence.status) is str
                and evidence.status in ("PASS", "NOT_CONNECTED", "NOT_RUN"),
                "extension_status",
            )
            extensions.append(
                {
                    "id": name,
                    "status": evidence.status,
                    "execution": "RUN",
                    "scope": "adapter_identity_conformance_only",
                }
            )
        missing = [name for name in row["required"] if stages[name]["status"] != "PASS"]
        results.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "anchor": row["anchor"],
                "result": "NOT_CONNECTED" if missing else "PASS_WITH_GAPS",
                "required_unavailable": missing,
                "stages": stages,
                "extensions": extensions,
            }
        )
    return JourneyReport(
        encode_json(
            {
                "schema": "fatwa.fast8-journey-conformance.v1",
                "baseline_sha": BASE_SHA,
                "contract_sha256": sha256(raw).hexdigest(),
                "integration_sha256": integration.sha256,
                "result": "NOT_CONNECTED"
                if any(r["result"] == "NOT_CONNECTED" for r in results)
                else "PASS_WITH_GAPS",
                "synthetic_only": True,
                "holds": [*observed["holds"], "U03/U10 OWNER_APPROVAL_PENDING"],
                "execution": {
                    "services": "PASS",
                    "http": "NOT_RUN",
                    "browser": "NOT_RUN",
                    "postgres": "NOT_RUN",
                    "owner_archives": "NOT_SUPPLIED",
                    "writes": False,
                    "network_requests": False,
                },
                "permission": {
                    "effect": observed["permission_gaps"]["effect"],
                    "allowed": observed["permission_gaps"]["allowed"],
                    "case_binding": "NOT_CONNECTED",
                },
                "scenarios": results,
            }
        )
    )
