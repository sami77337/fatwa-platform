"""Bounded adversarial regression runner over existing, read-only domain services.

Run in a dedicated CLI process. Source fault injection temporarily intercepts
fixed bundle reads in memory; it never edits a source, pin or application setting.
This module defines assertions, not an authorization engine.
"""

import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from apps.intake_workflow import fixtures
from apps.intake_workflow.intake import check_intake
from apps.permission_lab import services as lab
from apps.permission_lab import sources
from apps.policy_gap_engine import services as gap
from apps.workflow_invariants import engine as workflow

SCENARIO_PATH = Path(__file__).with_name("scenarios.json")
MAX_SCENARIOS = 64
MAX_MANIFEST_BYTES = 64 * 1024
BASE_SHA = "92fa517ecdefe3f1a92a1ab145ff55943474df44"
SOURCE_FILES = frozenset(
    {
        "__init__.py",
        "validator.py",
        "inventory.schema.json",
        "synthetic_inventory.json",
        "synthetic_review_excerpt.json",
    }
)


def load_scenarios() -> tuple[dict, str]:
    """Only the bundled bounded regression manifest; no external input path."""
    with SCENARIO_PATH.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("INVALID_SCENARIO_MANIFEST")
    manifest = json.loads(raw.decode("utf-8"))
    rows = manifest["scenarios"]
    if (
        manifest["schema"] != "fatwa.fast8-permission-probes.v1"
        or manifest["fixture_kind"] != "SYNTHETIC"
        or not 1 <= len(rows) <= MAX_SCENARIOS
        or len({row["id"] for row in rows}) != len(rows)
    ):
        raise ValueError("INVALID_SCENARIO_MANIFEST")
    return manifest, hashlib.sha256(raw).hexdigest()


def _decision(value) -> dict:
    return {
        "outcome": "DECISION",
        "effect": value.effect,
        "allowed": value.allowed,
        "valid_combination": value.valid_combination,
        "reason_codes": sorted({reason.code for reason in value.reasons}),
    }


def _permissions(request: dict) -> tuple[dict, dict]:
    try:
        first = _decision(lab.evaluate(request["actor"], request["action"], request["resource"]))
    except sources.SourceUnavailable:
        # The lab raises a closed source failure, not a Decision. Do not invent one.
        first = {
            "outcome": "SOURCE_UNAVAILABLE",
            "effect": None,
            "allowed": None,
            "valid_combination": None,
            "reason_codes": ["SOURCE_CONTRACT_UNAVAILABLE"],
        }
    second = _decision(gap.evaluate(gap.CandidateRequest(**request)))
    return first, second


@contextmanager
def _substituted_source(name: str):
    if name not in SOURCE_FILES:
        raise ValueError("INVALID_SOURCE_PROBE")
    target = Path(sources.__file__).resolve().parent / "upstream" / name
    original = Path.open
    raw = target.read_bytes()
    # Preserve syntax so rejection demonstrates identity pinning, not a JSON or
    # Python parse failure. Original bundle bytes remain untouched on disk.
    suffix = b"\r\n " if name.endswith(".json") else b"\r\n# FAST8 synthetic substitution\r\n"
    substituted = raw + suffix

    def opened(path, mode="r", *args, **kwargs):
        if path == target and mode == "rb":
            return io.BytesIO(substituted)
        return original(path, mode, *args, **kwargs)

    # Only raw I/O is faulted: actual loaders, hash checks and evaluators execute.
    with patch.object(Path, "open", opened):
        yield {
            "file": name,
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "substituted_sha256": hashlib.sha256(substituted).hexdigest(),
            "mode": "IN_MEMORY_READ_SUBSTITUTION",
        }


def _replay_boundary(spec: dict) -> dict:
    event = workflow.make_event(
        spec.get("event_case_key", spec["case_key"]), 1, "review", "start_review"
    )
    for edit in spec.get("edits", []):
        current = event
        for component in edit["path"][:-1]:
            current = current[component]
        current[edit["path"][-1]] = edit["value"]
    result = workflow.replay(
        {
            "schema": workflow.SCHEMA,
            "synthetic_fixtures_only": True,
            "case_key": spec["case_key"],
            "events": [event],
        }
    )
    step = result["steps"][0]
    return {
        "service": "workflow_invariants.replay",
        "reason_codes": [step["reason"]],
        "accepted": step["accepted"],
        "disposition": step["disposition"],
        "state_unchanged": (
            step["before"] == step["after"]
            and result["initial"] == result["final"]
            and step["state_changed"] is False
            and step["changed_paths"] == []
        ),
        "before_sha256": step["before_sha256"],
        "after_sha256": step["after_sha256"],
        "source_identity": result["source_identity"],
        "attempted_source_identity": event["source_identity"],
    }


def _duplicate_boundary() -> dict:
    raw = fixtures.synthetic_payload()
    checked = check_intake(raw, synthetic_fixtures_only=True)
    # Fixed fixture row identities, never a join on their nonunique external ID.
    rows = [checked.items[0], checked.items[3]]
    return {
        "service": "intake_workflow.check_intake",
        "reason_codes": sorted(
            set.intersection(
                *(
                    {finding["code"] for finding in row.validation_results["findings"]}
                    for row in rows
                )
            )
        ),
        "row_ordinals": [row.row_ordinal for row in rows],
        "statuses": [row.intake_status for row in rows],
        "external_ids_equal": rows[0].external_id == rows[1].external_id,
        "source_preserved": checked.parsed.raw == raw
        and all(
            raw[row.source.start : row.source.end].decode("utf-8") == row.source.text
            for row in rows
        ),
        "payload_sha256": checked.parsed.payload_sha256,
    }


def _matches(observed: dict, expected: dict) -> bool:
    return all(
        set(value) <= set(observed.get(key, []))
        if key == "reason_codes"
        else type(observed.get(key)) is type(value) and observed.get(key) == value
        for key, value in expected.items()
    )


def _run_one(row: dict) -> dict:
    result = {"id": row["id"], "category": row["category"], "status": "FAIL"}
    try:
        if "source_file" in row:
            with _substituted_source(row["source_file"]) as fault:
                first, second = _permissions(row["request"])
            result["source_fault"] = fault
        else:
            first, second = _permissions(row["request"])
        result.update(permission_lab=first, policy_gap_engine=second)
        expected = row["expected"]
        passed = _matches(first, expected["permission_lab"]) and _matches(
            second, expected["policy_gap_engine"]
        )
        if "domain" in row:
            domain = (
                _duplicate_boundary()
                if row["domain"]["kind"] == "duplicate_external_id"
                else _replay_boundary(row["domain"])
            )
            result["domain_boundary"] = domain
            passed = passed and _matches(domain, expected["domain_boundary"])
        result["status"] = "PASS" if passed else "FAIL"
        result["expected"] = expected
    except Exception:
        # Unexpected exceptions fail QA; never echo paths, text or credentials.
        result["error_code"] = "PROBE_EXECUTION_ERROR"
    return result


def run_suite(selected: tuple[str, ...] | None = None) -> dict:
    manifest, digest = load_scenarios()
    rows = manifest["scenarios"]
    identifiers = {row["id"] for row in rows}
    if selected is not None:
        if (
            type(selected) is not tuple
            or not 1 <= len(selected) <= MAX_SCENARIOS
            or any(type(value) is not str or value not in identifiers for value in selected)
            or len(set(selected)) != len(selected)
        ):
            raise ValueError("INVALID_SCENARIO_SELECTION")
        rows = [row for row in rows if row["id"] in selected]
    report = {
        "schema": manifest["schema"] + ".report",
        "status": "NOT_RUN",
        "scope": "FIXED_SYNTHETIC_REGRESSION_ONLY",
        "reviewed_base_sha": BASE_SHA,
        "scenario_sha256": digest,
        "scenario_count": len(rows),
        "source_commit": sources.SOURCE_COMMIT,
        "inventory_sha256": sources.INVENTORY_SHA256,
        "case_authorization_adapter": "NOT_CONNECTED",
        "owner_sources": "NOT_SUPPLIED",
        "owner_source_acceptance": "NOT_RUN",
        "policy_approval": "OWNER_APPROVAL_PENDING",
        "gates": {
            "B": "NOT_PASSED",
            "C/D/E": "HOLD",
            "Phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
        },
        "results": [],
        "counts": {"passed": 0, "failed": 0, "not_run": len(rows)},
    }
    try:
        # Establish healthy real sources before fault injection. Missing sources
        # must never produce a green adversarial run by coincidental denial.
        gap.load_evidence()
        lab.build_catalog()
    except sources.SourceUnavailable:
        report["reason_codes"] = ["SOURCE_CONTRACT_UNAVAILABLE"]
        return report
    results = [_run_one(row) for row in rows]
    report["results"] = results
    failed = sum(row["status"] == "FAIL" for row in results)
    report["counts"] = {"passed": len(rows) - failed, "failed": failed, "not_run": 0}
    report["status"] = "FAIL" if failed else "PASS"
    try:
        gap.load_evidence()
    except sources.SourceUnavailable:
        # Earlier observations are retained but cannot attest the final source state.
        report["status"] = "FAIL"
        report["reason_codes"] = ["SOURCE_CHANGED_DURING_RUN"]
    return report
