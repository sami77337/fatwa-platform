"""Bind additional original points to fresh exact-commit native/browser/recovery proof."""

import ast
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

PLAN = Path("docs/product/functional_continuation/scope_plan.json")
NEW_WORKFLOWS = {
    "apps.research_library.recovery_support": 4,
    "apps.material_import.recovery_support": 7,
    "apps.public_collections.recovery_support": 3,
    "apps.case_lifecycle.recovery_support": 1,
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path, started):
    path = Path(path)
    require(
        path.is_file() and path.stat().st_mtime >= started, "Missing or stale execution artifact"
    )
    return {"path": str(path), "sha256": sha(path.read_bytes()), "size": path.stat().st_size}


def test_class_exists(name):
    module, class_name = name.rsplit(".", 1)
    path = Path(module.replace(".", "/") + ".py")
    require(path.is_file(), "Declared test module is absent")
    require(
        any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in ast.parse(path.read_text()).body
        ),
        "Declared test class is absent",
    )


def write_continuation_receipt(execution, log_root, *, labels, browser_labels):
    plan = json.loads(PLAN.read_text())
    inventory = plan["source_inventory"]
    raw = Path(inventory["path"]).read_bytes()
    require(sha(raw) == inventory["sha256"], "Original requirement inventory changed")
    original = json.loads(raw)
    index = {row["original_id"]: row for row in original}
    require(
        len(index) == len(original) == inventory["denominator"] == 556,
        "Original denominator changed",
    )
    for prefix in ("specification", "decision"):
        require(
            sha(Path(inventory[prefix + "_path"]).read_bytes()) == inventory[prefix + "_sha256"],
            "Referenced source document changed",
        )
    previous = plan["previous_batch"]
    previous_raw = Path(previous["scope_plan_path"]).read_bytes()
    require(sha(previous_raw) == previous["scope_plan_sha256"], "Historical completed plan changed")
    previous_ids = {
        p["original_id"] for g in json.loads(previous_raw)["groups"] for p in g["points"]
    }
    require(
        previous_ids == set(previous["original_ids"])
        and len(previous_ids) == previous["credited_by_coordinator"] == 57,
        "Historical credited IDs changed",
    )
    groups = plan["groups"]
    points = [point for group in groups for point in group["points"]]
    identifiers = [point["original_id"] for point in points]
    require(
        len(set(identifiers)) == len(identifiers) == plan["candidate_count"],
        "Additional candidate count or uniqueness mismatch",
    )
    require(not set(identifiers) & previous_ids, "Previously credited points counted twice")
    require(
        not set(identifiers) & {point["original_id"] for point in plan["explicit_exclusions"]},
        "An excluded point was counted",
    )
    for point in points:
        require(
            all(
                point[key] == index[point["original_id"]][key]
                for key in ("original_text", "direct_spec_ids")
            ),
            "Original requirement was paraphrased or changed",
        )
    for group in groups:
        require(
            "PLANNED" not in group["implementation_state"],
            "An unimplemented planned group cannot be certified",
        )
        require(Path(group["contract"]).is_file(), "Functional contract is absent")
        require(
            group["service_test_labels"] and set(group["service_test_labels"]) <= set(labels),
            "A required service test family was not executed",
        )
        require(not group["pending_service_test_labels"], "Required test implementation is pending")
        for name in group["service_test_classes"]:
            test_class_exists(name)
        test_class_exists(group["browser"]["test_class"])
        require(
            group["browser"]["test_class"].rsplit(".", 1)[0] in browser_labels,
            "Required browser journey is not registered",
        )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    require(head == execution["tested_sha"], "Accounting commit differs from the tested commit")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], text=True
        ).strip(),
        "Accounting source is not clean",
    )
    major = execution["postgres"].split()[2].split(".")[0]
    require(major in {"17", "18"}, "Unsupported PostgreSQL evidence")
    stages = {stage["name"]: stage for stage in execution["stages"]}
    require(
        {"system", "migrations", "recording", "offline_client", "affected", "recovery"}
        <= stages.keys(),
        "Mandatory aggregate stage is missing",
    )
    logs = []
    for name, stage in stages.items():
        require(stage["exit_code"] == 0, "A failed stage cannot count completion")
        value = pin(log_root / (name + ".log"), execution["started_at_epoch"])
        require(value["sha256"] == stage["log_sha256"], "Stage log bytes changed")
        logs.append({**value, "stage": name, "command": stage["command"]})
    affected = (log_root / "affected.log").read_text()
    require(
        "\nOK\n" in affected and not re.search(r"\.\.\. skipped|OK \(skipped=", affected),
        "Service evidence failed or skipped required work",
    )
    test_count = re.search(r"Ran (\d+) tests? in", affected)
    require(test_count, "Real service test result is absent")
    recovery_path = Path(".local/qa/functional-continuation") / f"recovery-pg{major}.json"
    recovery_pin = pin(recovery_path, execution["started_at_epoch"])
    recovery = json.loads(recovery_path.read_text())
    require(
        recovery["tested_sha"] == head
        and recovery["status"] == "PASS"
        and recovery["postgres_major"] == int(major),
        "Recovery proof does not match this exact execution",
    )
    for field in (
        "source_unchanged",
        "source_frozen",
        "fresh_process_readers",
        "restored_private_storage_used",
        "restored_unchanged_after_readers",
        "all_restored_originals_verified_after_readers",
        "source_originals_unchanged",
        "encrypted",
    ):
        require(recovery[field] is True, "Incomplete encrypted recovery proof")
    require(recovery["plaintext_dump_present"] is False, "Plaintext database dump was retained")
    require(
        set(NEW_WORKFLOWS) <= set(recovery["additional_workflows"]),
        "A new workflow was omitted from recovery",
    )
    new_tables = []
    for helper, count in NEW_WORKFLOWS.items():
        app = helper.split(".")[1] + "_"
        selected = [name for name in recovery["tables"] if name.startswith(app)]
        require(len(selected) == count, "New recovery table inventory changed")
        require(
            all(recovery["tables"][name]["rows"] > 0 for name in selected),
            "An empty table cannot prove restore",
        )
        new_tables.extend(selected)
    require(
        any(
            ref["table"] == "research_library_libraryblob"
            and ref["backend"] == "private-filesystem-v1"
            for ref in recovery["durable_original_references"]
        ),
        "External library originals were omitted from recovery",
    )
    complete = execution["status"] == "PASS" and execution["browser_requested"] is True
    browser_proofs = []
    if complete:
        require("browser" in stages, "Protected browser stage was not executed")
        browser_log = (log_root / "browser.log").read_text()
        require(
            "\nOK\n" in browser_log and not re.search(r"\.\.\. skipped|OK \(skipped=", browser_log),
            "Protected browser journeys were skipped or failed",
        )
        for path in sorted({group["browser"]["result_path"] for group in groups}):
            record = pin(path, execution["started_at_epoch"])
            proof = json.loads(Path(path).read_text())
            require(
                proof.get("status") == "PASS"
                and proof.get("sandbox") is True
                and set(proof.get("widths", [])) == {320, 1280},
                "Protected responsive journey did not pass",
            )
            for field in ("page_errors", "external_requests"):
                value = proof.get(field)
                require(
                    value == [] or (type(value) is int and value == 0),
                    "Browser error or unexpected external request",
                )
            folder = Path(path).parent
            screenshots = sorted(folder.glob("*.png"))
            traces = sorted(folder.glob("*trace*.zip"))
            require(
                traces
                and all(
                    any(p.name.endswith(f"-{width}.png") for p in screenshots)
                    for width in (320, 1280)
                ),
                "Browser trace or responsive screenshot is absent",
            )
            artifacts = [pin(p, execution["started_at_epoch"]) for p in [*screenshots, *traces]]
            for trace in traces:
                with zipfile.ZipFile(trace) as archive:
                    require(
                        archive.testzip() is None
                        and any(name.endswith(".trace") for name in archive.namelist()),
                        "Protected browser trace is invalid",
                    )
            browser_proofs.append({**record, "artifacts": artifacts})
    count = len(identifiers) if complete else 0
    result = {
        "schema": "fatwa.functional-continuation-scope-receipt.v1",
        "status": "PASS" if complete else "PENDING_PROTECTED_BROWSER",
        "tested_sha": head,
        "scope_plan_sha256": sha(PLAN.read_bytes()),
        "source_inventory": inventory,
        "claim_boundary": plan["claim_boundary"],
        "denominator": len(index),
        "previous_credited_count": len(previous_ids),
        "candidate_count": len(identifiers),
        "completed_additional_original_ids": sorted(identifiers, key=int) if complete else [],
        "completed_additional_original_owner_points": count,
        "completed_additional_percentage": round(100 * count / len(index), 6),
        "overlap_with_previous_ids": [],
        "requested_10_to_12_percent_met": 10 <= 100 * count / len(index) <= 12,
        "postgres_major": int(major),
        "executed_test_labels": labels,
        "affected_tests": int(test_count[1]),
        "stage_receipts": logs,
        "browser_proofs": browser_proofs,
        "encrypted_recovery_proof": {
            **recovery_pin,
            "new_nonempty_tables": new_tables,
            "total_nonempty_tables": len(recovery["tables"]),
        },
        "groups": [
            {
                "id": g["id"],
                "title_ar": g["title_ar"],
                "additional_original_ids": [p["original_id"] for p in g["points"]],
                "completed": complete,
            }
            for g in groups
        ],
        "release_state": plan["release_state"],
    }
    output = Path(".local/qa/functional-continuation") / ("pg" + major)
    output.mkdir(parents=True, exist_ok=True)
    (output / "scope-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result
