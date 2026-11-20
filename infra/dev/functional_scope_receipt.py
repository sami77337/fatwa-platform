"""Bind the reviewed whole-point candidates to actual aggregate execution evidence.

This file does not infer semantic completeness from tests. The separately
reviewed scope plan records that assessment and its exclusions. This receipt
requires the unchanged original inventory, real command exits and protected
browser proofs before crediting any candidate for this execution.
"""

import hashlib
import json
import subprocess
from pathlib import Path

PLAN = Path("docs/product/functional_completion/scope_plan.json")
BROWSER_PROOFS = (
    "browser/result.json",
    "scholarly-browser/result.json",
    "public-browser/result.json",
    "export-browser/result.json",
    "quality-browser/result.json",
)


def write_scope_receipt(execution, output, *, labels):
    plan = json.loads(PLAN.read_text())
    inventory = Path(plan["source_inventory"]["path"])
    raw = inventory.read_bytes()
    original = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != plan["source_inventory"]["sha256"]:
        raise RuntimeError("Original requirement inventory changed")
    index = {row["original_id"]: row for row in original}
    if len(index) != len(original) or len(index) != plan["source_inventory"]["denominator"]:
        raise RuntimeError("Requirement denominator or identity changed")
    points = [point for group in plan["groups"] for point in group["points"]]
    identifiers = [point["original_id"] for point in points]
    if len(set(identifiers)) != len(identifiers) or len(points) != plan["candidate_count"]:
        raise RuntimeError("Candidate double-count or unexplained count")
    if set(identifiers) & {point["original_id"] for point in plan["explicit_exclusions"]}:
        raise RuntimeError("Excluded requirement was credited")
    for point in points:
        source = index[point["original_id"]]
        if any(source[key] != point[key] for key in ("original_text", "direct_spec_ids")):
            raise RuntimeError("A requirement's wording or scope changed")
    for group in plan["groups"]:
        if not set(group["service_test_labels"]).issubset(labels):
            raise RuntimeError("Candidate's required test family was not executed")
        for key in ("contract", "browser_test_file"):
            if not Path(group[key]).is_file():
                raise RuntimeError("Candidate contract or browser journey is absent")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != execution["tested_sha"]:
        raise RuntimeError("Execution and accounting source commits differ")
    if any(stage["exit_code"] != 0 for stage in execution["stages"]):
        raise RuntimeError("A failing verification stage cannot count completion")
    required_stages = {"system", "migrations", "recording", "affected", "recovery"}
    if not required_stages.issubset(stage["name"] for stage in execution["stages"]):
        raise RuntimeError("Aggregate service, schema or recovery evidence is absent")
    complete = execution["status"] == "PASS" and execution["browser_requested"] is True
    proofs = []
    if complete:
        if "browser" not in {stage["name"] for stage in execution["stages"]}:
            raise RuntimeError("Protected browser command was not executed")
        for name in BROWSER_PROOFS:
            path = Path(".local/qa/functional-completion") / name
            if path.stat().st_mtime < execution["started_at_epoch"]:
                raise RuntimeError("A previous run's browser proof cannot support this execution")
            raw = path.read_bytes()
            proof = json.loads(raw)
            if proof.get("status") != "PASS" or proof.get("sandbox") is not True:
                raise RuntimeError("A required protected journey did not pass")
            proofs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    count = len(points) if complete else 0
    result = {
        "schema": "fatwa.functional-scope-execution.v1",
        "status": "PASS" if complete else "PENDING_PROTECTED_BROWSER",
        "tested_sha": head,
        "postgres": execution["postgres"],
        "source_inventory": plan["source_inventory"],
        "scope_plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "claim_boundary": plan["claim_boundary"],
        "candidate_count": len(points),
        "completed_original_owner_points": count,
        "percentage_of_original_owner_points": round(100 * count / len(index), 6),
        "groups": [
            {
                "id": group["id"],
                "title_ar": group["title_ar"],
                "points": [point["original_id"] for point in group["points"]],
                "completed_count": len(group["points"]) if complete else 0,
                "contract": group["contract"],
                "service_test_labels": group["service_test_labels"],
            }
            for group in plan["groups"]
        ],
        "protected_browser_proofs": proofs,
        "explicit_exclusions": plan["explicit_exclusions"],
        "release_state": plan["release_state"],
    }
    (output / "scope-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
