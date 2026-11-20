"""Bind additional original points to fresh exact-commit native/browser/recovery proof."""

import ast
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

PLAN = Path("docs/product/functional_continuation/scope_plan.json")
PRIOR_TABLES = (
    "case_assignments_assignmentevent",
    "case_organization_organizationrevision",
    "content_reports_contentreport",
    "content_reports_reportevent",
    "research_workspace_researchcollection",
    "research_workspace_researchitem",
    "research_workspace_savedresearchsearch",
    "research_workspace_researchcollectionevent",
    "scholarly_links_lessoncategory",
    "scholarly_links_lessonseries",
    "scholarly_links_seriesversion",
    "scholarly_links_lesson",
    "scholarly_links_lessonversion",
    "scholarly_links_caserelation",
    "scholarly_links_caselessonlink",
    "scholarly_links_linkdecision",
    "public_knowledge_publicseries",
    "public_knowledge_publicrevision",
    "public_knowledge_publicaction",
    "selected_exports_exportjob",
    "selected_exports_exportevent",
    "selected_exports_exportartifact",
)
PRIOR_WORKFLOWS = (
    "apps.scholarly_links.recovery_support",
    "apps.public_knowledge.recovery_support",
    "apps.selected_exports.recovery_support",
)
NEW_WORKFLOWS = {
    "apps.research_library.recovery_support": (
        "research_library_libraryblob",
        "research_library_libraryitem",
        "research_library_libraryversion",
        "research_library_librarydecision",
    ),
    "apps.material_import.recovery_support": (
        "material_import_importbatch",
        "material_import_mappingrevision",
        "material_import_importplan",
        "material_import_importdecision",
        "material_import_groupresult",
        "material_import_importevent",
        "material_import_roundtripreceipt",
    ),
    "apps.public_collections.recovery_support": (
        "public_collections_collectionseries",
        "public_collections_collectionrevision",
        "public_collections_collectionaction",
    ),
    "apps.case_lifecycle.recovery_support": ("case_lifecycle_lifecycleevent",),
}
RESTORED_DENIAL_CHECKS = {
    "apps.research_library.recovery_support": {
        "missing_authority": 3,
        "missing_identity_provider": 3,
        "revoked_current_reader": 2,
        "revoked_public_release_actor": 1,
    },
    "apps.case_lifecycle.recovery_support": {
        "missing_authority": 3,
        "missing_identity_provider": 3,
        "revoked_current_reader": 3,
    },
}

# Keep the exact executed identities, including the assignment class's inherited
# journey. An unrelated replacement test must not satisfy the aggregate count.
# Legacy proofs retain their actual formats; the audio test emits only its test
# result in the aggregate log, not a fabricated JSON result or trace.
PRIOR_BROWSER_JOURNEYS = (
    (
        "tests.casework.test_functional_completion_browser.FunctionalCompletionBrowserTests."
        "test_same_case_claim_metadata_collect_compare_report_and_human_resolution",
        ".local/qa/functional-completion/browser/result.json",
        "modern",
    ),
    (
        "apps.case_assignments.browser_tests.AssignmentBrowserTests."
        "test_claim_mine_shared_release_on_mobile_and_desktop",
        ".local/qa/case-assignments/browser/assignments.json",
        "assignments",
    ),
    (
        "apps.case_assignments.browser_tests.AssignmentBrowserTests."
        "test_two_case_browser_journey_and_revoked_capabilities",
        ".local/qa/v6-casework/browser/evidence.json",
        "casework",
    ),
    (
        "apps.browser_audio.test_browser.BrowserAudioTests."
        "test_pause_resume_preserves_one_recording_and_excludes_paused_time",
        None,
        "execution_log",
    ),
    (
        "apps.scholarly_links.browser_tests.ScholarlyBrowserTests."
        "test_native_series_lessons_typed_links_review_and_filters",
        ".local/qa/functional-completion/scholarly-browser/result.json",
        "modern",
    ),
    (
        "apps.public_knowledge.browser_tests.PublicKnowledgeBrowserTests."
        "test_native_reviewed_profile_translation_release_and_revocation",
        ".local/qa/functional-completion/public-browser/result.json",
        "modern",
    ),
    (
        "apps.selected_exports.browser_tests.SelectedExportBrowserTests."
        "test_select_preview_queue_build_download_then_current_grant_revokes_retrieval",
        ".local/qa/functional-completion/export-browser/result.json",
        "modern",
    ),
    (
        "apps.data_quality.browser_tests.QualityBrowserTests."
        "test_current_diagnostic_refresh_and_operator_restore_preserve_case",
        ".local/qa/functional-completion/quality-browser/result.json",
        "quality",
    ),
)
NEW_BROWSER_JOURNEYS = (
    (
        "apps.research_library.browser_tests.LibraryBrowserTests."
        "test_native_external_video_rights_versions_and_public_revocation",
        ".local/qa/functional-continuation/library-browser/result.json",
        "modern",
    ),
    (
        "apps.research_library.offline_browser_tests.OfflineLibraryBrowserTests."
        "test_native_pwa_selection_offline_bytes_revocation_and_shortened_expiry",
        ".local/qa/functional-continuation/offline-browser/result.json",
        "modern",
    ),
    (
        "apps.material_import.browser_tests.MaterialImportBrowserTests."
        "test_native_independent_import_to_actual_library_version",
        ".local/qa/library-operations/import-browser/result.json",
        "modern",
    ),
    (
        "apps.public_collections.browser_tests.PublicCollectionsBrowserTests."
        "test_cross_case_native_curation_order_review_release_and_revocation",
        ".local/qa/functional-continuation/collections-browser/result.json",
        "modern",
    ),
    (
        "apps.case_lifecycle.browser_tests.LifecycleBrowserTests."
        "test_native_close_archive_restore_reopen_and_requester_followup",
        ".local/qa/functional-completion/lifecycle-browser/result.json",
        "modern",
    ),
)


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


def require_browser_journeys(log):
    require(
        "\nOK\n" in log and not re.search(r"\.\.\. skipped|OK \(skipped=", log),
        "Protected browser journeys were skipped or failed",
    )
    require(
        re.findall(r"^Ran (\d+) tests? in [^\n]+$", log, re.MULTILINE) == ["13"],
        "Exactly 13 protected browser journeys must complete",
    )
    # Output from HTTP handlers or Django startup may appear between a verbose
    # test header and its status. The one complete OK summary establishes success;
    # these headers establish which exact journeys made up that execution.
    observed = re.findall(r"^test_\w+ \(([\w.]+)\)", log, re.MULTILINE)
    expected = {row[0] for row in (*PRIOR_BROWSER_JOURNEYS, *NEW_BROWSER_JOURNEYS)}
    require(
        len(observed) == len(set(observed)) == len(expected) == 13 and set(observed) == expected,
        "A required protected browser journey was omitted or replaced",
    )
    return sorted(observed)


def browser_proof(journey, *, started, log_pin, family):
    test_id, path, schema = journey
    common = {"test_id": test_id, "family": family, "execution_log": log_pin}
    if schema == "execution_log":
        return {**common, "evidence_kind": "execution_log"}
    record = pin(path, started)
    proof = json.loads(Path(path).read_text())
    require(proof.get("status") == "PASS", "Protected browser proof did not pass")
    if schema == "casework":
        views = proof.get("views", [])
        require(
            {view.get("width") for view in views} == {320, 1280}
            and all(view.get("rtl") is True and view.get("no_overflow") is True for view in views)
            and proof.get("tests_run") == 1
            and proof.get("unsafe_url_requests") == 0,
            "Legacy casework responsive journey did not pass",
        )
        # This legacy source launches with chromium_sandbox=True; its JSON predates
        # a sandbox field. The exact executed test and protected invocation are
        # required, rather than adding an assertion the original proof never made.
    else:
        sandbox_field = "browser_sandbox" if schema == "assignments" else "sandbox"
        require(
            proof.get(sandbox_field) is True and set(proof.get("widths", [])) == {320, 1280},
            "Protected responsive journey did not pass",
        )
    error_field = "browser_errors" if schema == "quality" else "page_errors"
    for field in (error_field, "external_requests"):
        value = proof.get(field)
        require(
            value == [] or (type(value) is int and value == 0),
            "Browser error or unexpected external request",
        )
    folder = Path(path).parent
    screenshots = sorted(folder.glob("*.png"))
    traces = sorted(folder.glob("*trace*.zip"))
    require(
        all(any(p.name.endswith(f"-{width}.png") for p in screenshots) for width in (320, 1280)),
        "Responsive browser screenshot is absent",
    )
    if schema not in {"assignments", "casework"}:
        require(traces, "Protected browser trace is absent")
    artifacts = [pin(p, started) for p in [*screenshots, *traces]]
    for trace in traces:
        with zipfile.ZipFile(trace) as archive:
            require(
                archive.testzip() is None
                and any(name.endswith(".trace") for name in archive.namelist()),
                "Protected browser trace is invalid",
            )
    return {**common, **record, "evidence_kind": "json_and_execution_log", "artifacts": artifacts}


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
    require(
        {group["browser"]["result_path"] for group in groups}
        == {row[1] for row in NEW_BROWSER_JOURNEYS},
        "The continuation browser proof family changed",
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
    expected_workflows = {*PRIOR_WORKFLOWS, *NEW_WORKFLOWS}
    require(
        set(recovery["additional_workflows"]) == expected_workflows
        and len(recovery["additional_workflows"]) == len(expected_workflows),
        "A prior or new workflow was omitted from recovery",
    )
    new_tables = sorted(name for names in NEW_WORKFLOWS.values() for name in names)
    expected_tables = {*PRIOR_TABLES, *new_tables}
    require(
        len(PRIOR_TABLES) == 22
        and len(new_tables) == 15
        and len(expected_tables) == 37
        and set(recovery["tables"]) == expected_tables,
        "Exactly the 37 prior and new recovery tables are required",
    )
    require(
        all(
            type(recovery["tables"][name]["rows"]) is int and recovery["tables"][name]["rows"] > 0
            for name in expected_tables
        ),
        "An empty prior or new table cannot prove restore",
    )
    restored_results = recovery.get("restored_workflow_results")
    require(
        isinstance(restored_results, dict)
        and set(restored_results) == expected_workflows
        and all(isinstance(value, dict) and value for value in restored_results.values()),
        "All seven fresh-process workflow result records are required",
    )
    for helper, expected in RESTORED_DENIAL_CHECKS.items():
        result = restored_results[helper]
        require(
            result.get("denial_checks") == expected
            and all(type(value) is int for value in result["denial_checks"].values())
            and type(result.get("denied_read_count")) is int
            and result["denied_read_count"] == sum(expected.values()) == 9
            and result.get("positive_reads_after_denial") is True,
            "Restored library/lifecycle denial proof is incomplete or changed",
        )
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
    browser_test_ids = []
    if complete:
        require("browser" in stages, "Protected browser stage was not executed")
        require(
            os.environ.get("FATWA_BROWSER_SANDBOX") == "1",
            "Protected browser accounting requires sandboxed execution",
        )
        browser_log = (log_root / "browser.log").read_text()
        browser_test_ids = require_browser_journeys(browser_log)
        log_pin = pin(log_root / "browser.log", execution["started_at_epoch"])
        for family, journeys in (
            ("prior", PRIOR_BROWSER_JOURNEYS),
            ("additional", NEW_BROWSER_JOURNEYS),
        ):
            for journey in journeys:
                browser_proofs.append(
                    browser_proof(
                        journey,
                        started=execution["started_at_epoch"],
                        log_pin=log_pin,
                        family=family,
                    )
                )
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
        "protected_browser_tests": len(browser_test_ids),
        "protected_browser_test_ids": browser_test_ids,
        "prior_browser_journeys": len(PRIOR_BROWSER_JOURNEYS) if complete else 0,
        "additional_browser_journeys": len(NEW_BROWSER_JOURNEYS) if complete else 0,
        "browser_json_proofs": sum("path" in proof for proof in browser_proofs),
        "browser_log_only_proofs": sum("path" not in proof for proof in browser_proofs),
        "stage_receipts": logs,
        "browser_proofs": browser_proofs,
        "encrypted_recovery_proof": {
            **recovery_pin,
            "prior_nonempty_tables": sorted(PRIOR_TABLES),
            "prior_nonempty_table_count": len(PRIOR_TABLES),
            "new_nonempty_tables": new_tables,
            "new_nonempty_table_count": len(new_tables),
            "total_nonempty_tables": len(recovery["tables"]),
            "restored_workflow_results": restored_results,
            "fresh_process_denied_reads": sum(
                restored_results[helper]["denied_read_count"] for helper in RESTORED_DENIAL_CHECKS
            ),
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
