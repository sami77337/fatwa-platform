"""Offline, fail-closed validator for the full bounded V14 evidence mapping.

It verifies exact source-point text/status and Git blob pins. It does not
cryptographically authenticate GitHub logs or award owner acceptance.
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
PRODUCT = "762f322f26b21cf30f65a2453f360dd8738e9eec"
EXPECTED = {
    "recording-controls": [70, 77, 78, 408],
    "exact-pdf-and-time-preview": [543, 544, 545, 546, 549, 551, 552, 553, 554, 556],
    "closed-classification-editorial": [47, 121, 140, 169, 417, 419],
    "batched-rights-performance": [216, 408, 554],
    "startup-diagnostics": [428],
}
JOBS = {17: 135008889226, 18: 135008890057}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
METHOD = re.compile(r"[A-Za-z_]\w*\Z")


class EvidenceError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise EvidenceError(code)


def safe_path(path):
    require(
        type(path) is str and path and not path.startswith("/") and "\\" not in path
        and all(p not in ("", ".", "..") for p in path.split("/"))
        and all(32 < ord(c) < 127 for c in path),
        "unsafe_path",
    )
    return path


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def pinned(ref, read_file):
    path = safe_path(ref["path"])
    sha = ref["blob_sha"]
    require(type(sha) is str and HEX40.fullmatch(sha), "invalid_blob_sha")
    try:
        raw = read_file(path)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("source_missing") from exc
    require(type(raw) is bytes and git_blob(raw) == sha, "source_changed")
    return raw


def verify(data, candidate, read_file):
    require(data["schema"] == "fatwa.v14.full-candidate-observation.v1", "schema")
    require(data["source_sha"] == BASE and data["product_tested_sha"] == PRODUCT, "sha")
    require(
        data["status_upgrades"] == 0 and data["acceptance"] == "HOLD"
        and data["percentage"] is None,
        "acceptance_inflation",
    )
    require(len(data["groups"]) == len(EXPECTED), "group_count")
    source_groups = {g["id"]: g for g in candidate["groups"]}
    seen, points, methods = set(), {}, set()
    for group in data["groups"]:
        gid = group["id"]
        require(gid in EXPECTED and gid not in seen, "duplicate_or_unknown_group")
        seen.add(gid)
        source = source_groups.get(gid)
        require(source is not None, "source_group_missing")
        require([p["id"] for p in group["points"]] == EXPECTED[gid], "point_order")
        original = {p["original_id"]: p for p in source["point_mappings"]}
        for point in group["points"]:
            pid = point["id"]
            require(pid in original, "missing_point")
            src = original[pid]
            require(
                point["original_text"] == src["original_text"]
                and point["preserved_status"] == src["preserved_status"]
                and point["bounded_relevance"] == src["bounded_relevance"],
                "owner_text_or_status_changed",
            )
            record = (point["original_text"], point["preserved_status"])
            require(pid not in points or points[pid] == record, "conflicting_duplicate_point")
            points[pid] = record
        expected_code = {c["path"] for c in source["code"]}
        actual_code = {c["path"] for c in group["code"]}
        require(actual_code == expected_code, "code_inventory_mismatch")
        for ref in group["code"]:
            pinned(ref, read_file)
        expected_tests = {}
        for item in source["proposed_positive_tests"]:
            expected_tests[item["symbol"]] = "positive"
        for item in source["proposed_negative_tests"]:
            expected_tests[item["symbol"]] = "negative"
        require(len(group["tests"]) == len(expected_tests), "test_count")
        observed = set()
        for test in group["tests"]:
            symbol = test["symbol"]
            tokens = symbol.split(".")
            short_symbol = ".".join(tokens[-2:])
            require(short_symbol in expected_tests and symbol not in observed, "test_symbol")
            observed.add(short_symbol)
            require(test["kind"] == expected_tests[short_symbol], "test_kind")
            require(len(tokens) >= 3 and all(METHOD.fullmatch(t) for t in tokens), "symbol_format")
            expected_path = "/".join(tokens[:-2]) + ".py"
            require(test["path"] == expected_path, "test_path")
            raw = pinned(test, read_file)
            require(
                re.search(rb"(?m)^\s*def " + tokens[-1].encode() + rb"\s*\(", raw),
                "method_missing",
            )
            line = tokens[-1] + " (" + symbol + ") ... ok"
            require(test["pg17_line"] == line and test["pg18_line"] == line, "pass_line")
            methods.add(symbol)
        require(observed == set(expected_tests), "test_inventory_mismatch")
    require(seen == set(EXPECTED), "group_missing")
    require(len(points) == 22 and len(methods) == 20, "inventory_totals")
    require(data["owner_points_unique"] == sorted(points.keys()), "point_index")
    require(data["unique_named_methods"] == len(methods), "method_index")
    require(data["candidate_point_occurrences"] == 24, "occurrence_count")
    require(len(data["jobs"]) == 2, "jobs")
    for job in data["jobs"]:
        major = job["postgres_major"]
        require(major in JOBS and job["job_id"] == JOBS[major], "job_attribution")
        require(
            job["tested_sha"] == PRODUCT and job["tests_count"] == 130
            and job["browser_recovery_exit_0"] is True,
            "run_evidence",
        )
    require({j["postgres_major"] for j in data["jobs"]} == {17, 18}, "major_matrix")
    require(any("ROOT_CAUSE_UNKNOWN" in x for x in data["limits"]), "startup_limit")
    require(any("NOT_VERIFIED" in x for x in data["limits"]), "pdf_limit")
    return {
        "groups": len(seen), "unique_owner_points": len(points),
        "candidate_occurrences": 24, "named_test_methods": len(methods),
        "postgresql": [17, 18], "status_upgrades": 0, "acceptance": "HOLD",
    }


def main():
    require(sys.argv[1:] in ([], ["--check"]), "arguments")
    data = json.loads((HERE / "observed_execution_full.json").read_text(encoding="utf-8"))
    candidate = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
    def read_file(path):
        return subprocess.check_output(["git", "show", f"{PRODUCT}:{path}"], cwd=ROOT)
    print(json.dumps(verify(data, candidate, read_file), sort_keys=True))


if __name__ == "__main__":
    main()
