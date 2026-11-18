"""Extend immutable V12 scope with bounded V13 evidence; no DB/network/product writes."""

import ast
import copy
import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_SHA = "5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8"
PREFIX = "docs/product/v12_scope_evidence/"
REPO = "https://github.com/sami77337/fatwa-platform"


def read(name):
    return json.loads((HERE / name).read_text())


def pinned(path, sha):
    assert re.fullmatch(r"[0-9a-f]{40}", sha), "exact commit required"
    assert not path.startswith("/") and ".." not in Path(path).parts
    return subprocess.check_output(["git", "show", f"{sha}:{path}"], cwd=ROOT)


def baseline():
    manifest = read("baseline_manifest.json")
    assert manifest["base_sha"] == BASE_SHA and manifest["scope_base"] == PREFIX[:-1]
    data = {}
    for name, expected in manifest["files"].items():
        raw = pinned(PREFIX + name, BASE_SHA)
        assert hashlib.sha256(raw).hexdigest() == expected, (name, "baseline changed")
        data[name] = json.loads(raw)
    rows = data["matrix.json"]
    assert [int(row["original_id"]) for row in rows] == list(range(1, 557))
    assert len(data["specifications.json"]) == 479
    assert len(data["decisions.json"]) == 77
    assert len({row["original_id"] for row in data["decisions.json"]}) == 72
    return data


def reference(value, sha):
    path, _, symbol = value.partition("#")
    raw = pinned(path, sha)
    line, end = 1, len(raw.splitlines())
    if symbol:
        found = []

        def walk(node, parents=()):
            for child in ast.iter_child_nodes(node):
                named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                names = (*parents, child.name) if named else parents
                if named and (".".join(names) == symbol or child.name == symbol):
                    found.append(child)
                walk(child, names)

        walk(ast.parse(raw))
        assert len(found) == 1, (value, "missing or ambiguous symbol")
        line, end = found[0].lineno, found[0].end_lineno
    return {
        "path": path,
        "symbol": symbol or None,
        "sha": sha,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "line": line,
        "end_line": end,
        "url": f"{REPO}/blob/{sha}/{path}#L{line}-L{end}",
    }


def check_execution(group, refs):
    """Require observed exact-head positive/negative tests on both PG majors."""
    receipts = group["receipts"]
    assert {r["postgres_major"] for r in receipts} == {17, 18}
    assert len(receipts) == 2, "one exact-head receipt per major"
    for receipt in receipts:
        assert receipt["head_sha"] == group["product_sha"]
        assert receipt["conclusion"] == "success" and receipt["status"] == "completed"
        assert receipt["run_id"] > 0 and receipt["job_id"] > 0
        source = read(receipt["excerpt"])
        assert source["head_sha"] == receipt["head_sha"]
        assert source["run_id"] == receipt["run_id"] and source["job_id"] == receipt["job_id"]
        lines = source["lines"]
        assert any("TESTED_SHA=" + receipt["head_sha"] in line for line in lines)
        version = f"SYNTHETIC_POSTGRES=postgres (PostgreSQL) {receipt['postgres_major']}."
        assert any(version in line for line in lines), "actual PostgreSQL major must be observed"
        for ref in refs:
            assert ref["symbol"], "test must name its executed method"
            method = ref["symbol"].split(".")[-1]
            module = ref["path"].removesuffix(".py").replace("/", ".")
            assert any(
                method + " (" in line and module + "." in line and line.endswith(" ... ok")
                for line in lines
            ), (receipt["postgres_major"], ref, "missing actual pass")
        if group["browser_test"]:
            assert any("FATWA_BROWSER_SANDBOX: 1" in line for line in lines)


def groups_for(assessment):
    assert assessment["base_sha"] == BASE_SHA
    assert assessment["acceptance"] == "HOLD" and assessment["percentage"] is None
    groups = copy.deepcopy(assessment["groups"])
    assert len({g["id"] for g in groups}) == len(groups)
    for group in groups:
        assert group["state"] in {"PENDING", "VERIFIED_BOUNDED"}
        points = group["candidate_owner_points"]
        assert points and len(set(points)) == len(points)
        assert all(type(n) is int and 1 <= n <= 556 for n in points)
        assert group["remaining"] and group["selection"].startswith("EXPLICIT_")
        if group["state"] == "PENDING":
            assert group["credited_owner_points"] == []
            assert group["product_sha"] is None and group["bounded_claim"] is None
            assert not any(
                group[k] for k in ("code", "positive_tests", "negative_tests", "receipts")
            )
            assert group["browser_test"] is None
            continue
        sha = group["product_sha"]
        for attempt in read("execution_history.json")["entries"]:
            assert not (
                attempt["sha"] == sha
                and attempt["security_status"] == "BLOCKED"
                and group["id"] in attempt["blocked_groups"]
            ), "known security blocker prevents affected scope credit despite successful CI"
        assert group["browser_test"], (
            "V13 user-facing groups require protected connected UI evidence"
        )
        assert group["credited_owner_points"]
        assert set(group["credited_owner_points"]) <= set(points)
        assert group["bounded_claim"] and all(
            group[k] for k in ("code", "positive_tests", "negative_tests")
        )
        assert set(group["positive_tests"]).isdisjoint(group["negative_tests"])
        for kind in ("code", "positive_tests", "negative_tests"):
            group[kind] = [reference(value, sha) for value in group[kind]]
        tests = [*group["positive_tests"], *group["negative_tests"]]
        if group["browser_test"]:
            group["browser_test"] = reference(group["browser_test"], sha)
            tests.append(group["browser_test"])
        check_execution(group, tests)
    return groups


def render():
    old = baseline()
    groups = groups_for(read("assessment.json"))
    source = read("source_bytes.json")
    attested = source["independent_attestation"] is not None
    rows = copy.deepcopy(old["matrix.json"])
    for row in rows:
        number = int(row["original_id"])
        candidates = [g for g in groups if number in g["candidate_owner_points"]]
        verified = [
            g
            for g in candidates
            if g["state"] == "VERIFIED_BOUNDED" and number in g["credited_owner_points"]
        ]
        row["v13"] = {
            "candidate_group_ids": [g["id"] for g in candidates],
            "verified_group_ids": [g["id"] for g in verified],
            "evidence_shas": sorted({g["product_sha"] for g in verified}),
            "assessment_effect": "EVIDENCE_ADDED_NO_STATUS_UPGRADE"
            if verified
            else "NOT_YET_ASSESSED",
            "remaining": [g["remaining"] for g in candidates],
            "attested_original_excel_row": row["source_locator"]["parsed_index"] + 2
            if attested
            else None,
            "excel_row_basis": "PARENT_LOCAL_ATTESTATION" if attested else None,
        }
    for old_row, new_row in zip(old["matrix.json"], rows, strict=True):
        assert {k: new_row[k] for k in old_row} == old_row
    assert source["local_status"] == "SOURCE_BYTES_UNAVAILABLE"
    assert source["local_reference_workbook_byte_verification"] is False
    assert source["reference_workbook_uploaded_to_repository"] is False
    assert source["artifact_role"] == "DERIVED_REFERENCE_WORKBOOK_NOT_AUTHORING_DOCUMENT"
    authoring = source["authoring_document"]
    assert authoring["filename"] == "542.docx" and authoring["byte_validation"] == "UNVERIFIED"
    assert authoring["byte_identity_proved_by_workbook_match"] is False
    assert authoring["acceptance_inferred"] is False
    # A supplied independent report may be added later without rewriting local status.
    if source["independent_attestation"] is not None:
        report = source["independent_attestation"]
        assert report["environment"] != "this_worktree"
        assert report["status"] == "VERIFIED_IN_OTHER_ENVIRONMENT"
        assert report["sha256"] == source["parent_reported_sha256"]
        assert report["size"] == source["parent_reported_size"]
        assert report["receipt"] and report["scope_comparison"]
        assert report["verification_basis"] == "PARENT_SUPPLIED_ATTESTATION_NOT_LOCALLY_REEXECUTED"
        assert report["receipt_bytes_inspected_here"] is False
        comparison = report["scope_comparison"]
        assert comparison["compared_base_sha"] == BASE_SHA
        assert comparison["whole_workbook_string_equivalence"] is False
        assert comparison["date_serialization_differences"]["count"] == 17
        assert comparison["formula_comparison"] == "SAVED_VALUES_ONLY"
        assert comparison["recalculation"] is False
    summary = {
        "base_sha": BASE_SHA,
        "owner_points": len(rows),
        "specification_clauses": 479,
        "decision_ids": 72,
        "decision_occurrences": 77,
        "preserved_status_counts": dict(Counter(r["engineering_status"] for r in rows)),
        "candidate_points": sum(bool(r["v13"]["candidate_group_ids"]) for r in rows),
        "verified_points": sum(bool(r["v13"]["verified_group_ids"]) for r in rows),
        "status_upgrades": 0,
        "acceptance": "HOLD",
        "percentage": None,
        "source_bytes_local": source["local_status"],
        "source_bytes_parent_attested": attested,
    }
    products = {
        "matrix.json": rows,
        "evidence.json": {"historical": old["evidence.json"], "v13": groups},
        "summary.json": summary,
    }
    output = {
        name: json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        for name, value in products.items()
    }
    csvout = io.StringIO(newline="")
    writer = csv.writer(csvout, lineterminator="\n")
    writer.writerow(
        [
            "original_id",
            "original_text",
            "direct_spec_ids",
            "baseline_status",
            "candidate_groups",
            "verified_groups",
            "evidence_shas",
            "remaining",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["original_id"],
                row["original_text"],
                ";".join(row["direct_spec_ids"]),
                row["engineering_status"],
                ";".join(row["v13"]["candidate_group_ids"]),
                ";".join(row["v13"]["verified_group_ids"]),
                ";".join(row["v13"]["evidence_shas"]),
                " / ".join(row["v13"]["remaining"]),
            ]
        )
    output["matrix.csv"] = csvout.getvalue()
    lines = [
        "# V13 — امتداد محفوظ للنقاط الأصلية",
        "",
        "الترشيح ليس دليل تنفيذ؛ الحالة الأصلية محفوظة ولا قبول أو نسبة جديدة.",
        "",
        "| النقطة والنص الأصلي | SPEC | تصنيف V12 المحفوظ | مرشح V13 | مثبت V13 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        fields = [
            row["original_id"] + " — " + row["original_text"],
            ", ".join(row["direct_spec_ids"]),
            row["engineering_status"],
            ", ".join(row["v13"]["candidate_group_ids"]),
            ", ".join(row["v13"]["verified_group_ids"]) or "لم يثبت في هذه الإضافة",
        ]
        lines.append(
            "| "
            + " | ".join(str(v).replace("|", "\\|").replace("\n", "<br>") for v in fields)
            + " |"
        )
    output["MATRIX.md"] = "\n".join(lines) + "\n"
    evidence = [
        "# V13 — أدلة محدودة منفصلة عن الترشيح",
        "",
        "[أدلة V12 التاريخية](../v12_scope_evidence/EVIDENCE.md) محفوظة برؤوسها؛ الترشيح التالي ليس إثبات تنفيذ.",
    ]
    for group in groups:
        evidence += [
            "",
            "## " + group["id"],
            "",
            "الحالة: **" + group["state"] + "**",
            "",
            "الهدف المحدد: " + group["bounded_goal"],
            "",
            "الحدود: " + group["remaining"],
            "",
            "النقاط المرشحة: " + ", ".join(map(str, group["candidate_owner_points"])),
            "",
            "النقاط التي أضيف لها دليل مثبت: "
            + (", ".join(map(str, group["credited_owner_points"])) or "لا شيء بعد"),
        ]
        if group["state"] == "VERIFIED_BOUNDED":
            evidence += [
                "",
                "المثبت فقط: " + group["bounded_claim"],
                "",
                "الرأس: `" + group["product_sha"] + "`",
            ]
            for kind in ("code", "positive_tests", "negative_tests"):
                evidence += ["", "### " + kind, ""]
                evidence += [
                    f"- [{ref['path']} — {ref['symbol'] or 'file'}]({ref['url']})"
                    for ref in group[kind]
                ]
            for receipt in group["receipts"]:
                evidence += [
                    f"- [PG{receipt['postgres_major']} job{receipt['job_id']}]({REPO}/actions/runs/{receipt['run_id']}/job/{receipt['job_id']}) — exact-head PASS"
                ]
    output["EVIDENCE.md"] = "\n".join(evidence) + "\n"
    return output


def draft_anchors_document(draft=None):
    """Validate static anchors separately; their existence grants no test credit."""
    draft = read("draft_anchors.json") if draft is None else draft
    assert draft["review_kind"] == "STATIC_CODE_REVIEW_ONLY"
    assert draft["execution_state"] == "PENDING"
    assert draft["credited_owner_points"] == []
    assert draft["source_attribution"] == "PARENT_LOCAL_ATTESTATION_PRESERVED_SEPARATELY"
    candidates = {g["id"]: g for g in read("assessment.json")["groups"]}
    assert {g["id"] for g in draft["groups"]} == set(candidates)
    assert len(draft["groups"]) == len(candidates)
    rows = baseline()["matrix.json"]
    lines = [
        "# V13 static code anchors — execution pending",
        "",
        f"Read SHA: `{draft['read_sha']}`. **STATIC_CODE_REVIEW_ONLY; PENDING execution.**",
        "",
        "These exact code/test symbols were read and resolved at this SHA. Their existence is",
        "not an executed PASS, independent security review or credited scope point. All original",
        "556 classifications and prior evidence remain unchanged. Final execution evidence must",
        "name its own actual SHA and both PostgreSQL majors plus protected Chrome.",
        "",
        "Source-byte attribution remains in [SOURCE_BYTES.md](SOURCE_BYTES.md): parent-local",
        "attestation, not reference-workbook byte verification in this Cloud environment.",
    ]
    for group in draft["groups"]:
        lines += ["", "## " + group["id"], "", group["bounded_scope_to_verify"], ""]
        lines += ["Candidate points retain original SPEC links; none is credited here:", ""]
        for number in candidates[group["id"]]["candidate_owner_points"]:
            row = rows[number - 1]
            specs = row["direct_spec_ids"] + row["additional_reverse_spec_ids"]
            lines.append(f"- {number}: {row['original_text']} — SPEC: {', '.join(specs) or 'none'}")
        for kind in ("code", "positive_tests", "negative_tests", "browser_candidates"):
            lines += ["", "### " + kind, ""]
            assert len(group[kind]) == len(set(group[kind]))
            for value in group[kind]:
                ref = reference(value, draft["read_sha"])
                if kind != "code":
                    assert ref["symbol"] and ref["symbol"].split(".")[-1].startswith("test_")
                lines.append(f"- [{value}]({ref['url']})")
            if not group[kind]:
                lines.append("Pending integrated anchor; no execution claim.")
        assert not set(group["positive_tests"]) & set(group["negative_tests"])
        lines += ["", "### Remaining limits", ""] + ["- " + gap for gap in group["gaps"]]
    return "\n".join(lines) + "\n"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = render()
    outputs["DRAFT_ANCHORS.md"] = draft_anchors_document()
    for name, value in outputs.items():
        if args.check:
            assert (HERE / name).read_text() == value, (name, "output drift")
        else:
            (HERE / name).write_text(value)
    print(
        "PASS: 556 preserved rows; bounded V13 attribution; no status upgrades or local XLSX claim"
    )


if __name__ == "__main__":
    main()
