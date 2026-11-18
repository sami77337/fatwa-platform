"""Fail-closed local validation of bounded V14 execution observations.

The receipt is a bridge from known CI runs to selected owner-point candidates,
not a formal requirement acceptance or an independently authenticated log.
Use a checkout containing the pinned V14 parent commit. No network is used.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = "6b4f77e29ccb1f21d48ad3d77f5e63d3be953fab"
EXPECTED_GROUPS = {
    "recording-controls": (70, 77, 78),
    "exact-pdf-and-time-preview": (545, 546, 553, 554),
    "closed-classification-editorial": (121, 140, 417),
    "batched-rights-performance": (216,),
}
EXPECTED_JOBS = {17: 134656248871, 18: 134656248333}
EXPECTED_COUNTS = {
    "PARTIAL": 303,
    "DECISION": 52,
    "NOT_IMPLEMENTED": 168,
    "OUT_OF_SCOPE": 33,
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
METHOD = re.compile(r"[A-Za-z_]\w*\Z")
RUN_URL = "https://github.com/sami77337/fatwa-platform/actions/runs/44261673950"


class EvidenceError(ValueError):
    """No arbitrary source bytes or CI log payload in exceptions."""


def require(condition, code):
    if not condition:
        raise EvidenceError(code)


def git_blob(raw):
    """The SHA-1 of one Git blob, not a SHA-256 of its file bytes."""
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def safe_path(path):
    require(
        type(path) is str
        and path
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in ("", ".", "..") for part in path.split("/"))
        and all(32 < ord(c) < 127 for c in path),
        "unsafe_repository_path",
    )
    return path


def git_reader(path):
    safe_path(path)
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT)


def source_test_ref(ref, read_pinned):
    path = safe_path(ref["path"])
    symbol = ref["symbol"]
    require(type(symbol) is str and "." in symbol, "invalid_test_symbol")
    tokens = symbol.split(".")
    require(len(tokens) >= 3 and all(METHOD.fullmatch(t) for t in tokens), "invalid_test_symbol")
    expected_path = "/".join(tokens[:-2]) + ".py"
    require(path == expected_path and path.endswith(".py"), "test_source_mismatch")
    raw = pinned_file(ref, read_pinned)
    method = tokens[-1]
    require(
        re.search(rb"(?m)^\s*def " + method.encode() + rb"\s*\(", raw) is not None,
        "test_method_missing_in_source",
    )
    return symbol


def pinned_file(ref, read_pinned):
    path = safe_path(ref["path"])
    sha = ref["blob_sha"]
    require(type(sha) is str and HEX40.fullmatch(sha), "invalid_blob_pin")
    try:
        raw = read_pinned(path)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("pinned_source_unavailable") from exc
    require(type(raw) is bytes and git_blob(raw) == sha, "pinned_source_changed")
    return raw


def check(data, candidate, read_pinned):
    require(data["schema"] == "fatwa.v14.bounded-observed-evidence.v1", "schema_changed")
    require(data["product_sha"] == BASE and data["pr_number"] == 233, "wrong_product_head")
    require(data["run_url"] == RUN_URL, "wrong_workflow")
    require(
        data["state"] == "OBSERVED_BOUNDED_NO_ACCEPTANCE"
        and data["source_matrix_unchanged"] is True
        and data["evidence_kind"] == "DOCUMENTING_EXISTING_EXECUTION_NOT_NEW_PRODUCT_TEST"
        and data["status_upgrades"] == 0
        and data["acceptance"] == "HOLD"
        and data["percentage"] is None,
        "unsupported_acceptance_claim",
    )
    require(data["baseline_status_counts"] == EXPECTED_COUNTS, "baseline_counts_changed")
    candidate_groups = {g["id"]: g for g in candidate["groups"]}
    require(set(candidate_groups) >= set(EXPECTED_GROUPS), "candidate_mapping_missing")
    groups = data["groups"]
    require(len(groups) == len(EXPECTED_GROUPS), "wrong_group_count")
    seen_groups, all_points, tests = set(), set(), set()
    for group in groups:
        gid = group["candidate_group"]
        require(gid in EXPECTED_GROUPS and gid not in seen_groups, "wrong_or_duplicate_group")
        seen_groups.add(gid)
        points = group["owner_points"]
        require([p["id"] for p in points] == list(EXPECTED_GROUPS[gid]), "owner_point_drift")
        candidate_points = {
            p["original_id"]: p for p in candidate_groups[gid]["point_mappings"]
        }
        for point in points:
            pid = point["id"]
            require(pid not in all_points and pid in candidate_points, "duplicate_or_missing_point")
            all_points.add(pid)
            original = candidate_points[pid]
            require(
                point["original_text"] == original["original_text"]
                and point["preserved_status"] == original["preserved_status"],
                "original_source_or_status_modified",
            )
        require(group["bounded_claim"] and group["remaining"], "claim_or_limits_missing")
        require(group["proof_scope"] == "NAMED_TESTS_ON_EXACT_HEAD_NOT_FORMAL_ACCEPTANCE", "proof_scope_changed")
        require(group["code"] and group["positive_tests"] and group["negative_tests"], "missing_evidence")
        for ref in group["code"]:
            pinned_file(ref, read_pinned)
        for ref in group["positive_tests"] + group["negative_tests"]:
            tests.add(source_test_ref(ref, read_pinned))
    require(seen_groups == set(EXPECTED_GROUPS), "incomplete_groups")
    receipts = data["executions"]
    require(len(receipts) == 2, "missing_postgres_major")
    seen_majors = set()
    for run in receipts:
        major = run["postgres_major"]
        require(major in EXPECTED_JOBS and major not in seen_majors, "wrong_or_duplicate_major")
        seen_majors.add(major)
        require(
            run["run_id"] == 44261673950
            and run["job_id"] == EXPECTED_JOBS[major]
            and run["tested_sha"] == BASE
            and run["conclusion"] == "success"
            and run["attribution"] == "DIRECT_GITHUB_DECODED_JOB_LOG_READ"
            and run["test_count_observed"] == 124
            and run["browser_sandboxed"] is True
            and run["restored_target_http"] == "PASS",
            "job_attribution_or_browser_mismatch",
        )
        observed = run["observed_tests"]
        require(len(observed) == len(tests), "wrong_named_test_count")
        require({r["symbol"] for r in observed} == tests, "missing_named_test")
        for row in observed:
            name = row["symbol"].rsplit(".", 1)[-1]
            require(
                row["observed_line"] == f"{name} ({row['symbol']}) ... ok",
                "named_test_not_passed",
            )
    require(seen_majors == {17, 18}, "incomplete_postgres_matrix")
    require(
        len(data["limits"]) >= 3
        and "COMPLETE" in " ".join(data["limits"])
        and "NOT_VERIFIED" in " ".join(data["limits"]),
        "limits_missing",
    )
    return {"groups": len(groups), "owner_points_with_bounded_observations": len(all_points),
            "test_methods_observed_on_each_major": len(tests), "postgreSQL_majors": [17, 18],
            "acceptance": "HOLD", "new_completed_points": 0}


def main():
    require(sys.argv[1:] in ([], ["--check"]), "invalid_arguments")
    data = json.loads((HERE / "observed_execution.json").read_text(encoding="utf-8"))
    candidate = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
    result = check(data, candidate, git_reader)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
