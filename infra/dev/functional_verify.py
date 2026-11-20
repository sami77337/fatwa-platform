"""Verify the completed synthetic workflows and bind evidence to the tested commit."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LABELS = [
    "tests.wave7_foundation.test_runner_lifecycle",
    "tests.casework.test_functional_continuation_receipt",
    "apps.case_assignments.tests",
    "apps.case_assignments.review_tests",
    "apps.case_organization.tests",
    "apps.research_workspace.test_collections",
    "apps.content_reports.tests",
    "apps.content_reports.test_review",
    "apps.content_reports.test_requester_review",
    "apps.team_workspace.tests",
    "tests.casework.test_v7_workspace",
    "apps.mufti_workspace.tests",
    "apps.mufti_workspace.workflow_tests",
    "apps.mufti_workspace.journey_tests",
    "apps.research_workspace.tests",
    "apps.research_workspace.test_source_rights",
    "apps.requester_portal.tests",
    "apps.requester_portal.workflow_tests",
    "apps.browser_audio.test_boundaries",
    "apps.scholarly_links.tests",
    "apps.public_knowledge.tests",
    "apps.public_knowledge.test_scholarly",
    "apps.library_preview.tests",
    "apps.selected_exports.tests",
    "apps.selected_exports.test_durability",
    "apps.data_quality.tests",
    "apps.data_quality.test_review",
    "apps.research_library.tests",
    "apps.research_library.test_http",
    "apps.research_library.test_storage",
    "apps.research_library.test_offline",
    "apps.research_library.test_recovery",
    "apps.material_import.test_formats",
    "apps.material_import.tests",
    "apps.material_import.test_roundtrip",
    "apps.material_import.test_recovery",
    "apps.public_collections.tests",
    "apps.public_collections.test_scholarly",
    "apps.public_collections.test_recovery",
    "apps.case_lifecycle.tests",
    "apps.case_lifecycle.test_delivery",
    "apps.case_lifecycle.test_recovery",
    "apps.case_attachments.storage_gc_tests",
]

BROWSER_LABELS = [
    "tests.casework.test_functional_completion_browser",
    "apps.case_assignments.browser_tests",
    "apps.browser_audio.test_browser.BrowserAudioTests.test_pause_resume_preserves_one_recording_and_excludes_paused_time",
    "apps.scholarly_links.browser_tests",
    "apps.public_knowledge.browser_tests",
    "apps.selected_exports.browser_tests",
    "apps.data_quality.browser_tests",
    "apps.research_library.browser_tests",
    "apps.research_library.offline_browser_tests",
    "apps.material_import.browser_tests",
    "apps.public_collections.browser_tests",
    "apps.case_lifecycle.browser_tests",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--pg-bin", required=True)
    args = parser.parse_args()
    if args.browser and os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
        parser.error("Protected browser evidence requires FATWA_BROWSER_SANDBOX=1")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != os.environ.get("EXPECTED_SHA", head):
        parser.error("Checkout differs from the requested commit")
    def clean_source():
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], text=True
        ).strip():
            parser.error("Verification requires a clean committed source tree")
        if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != head:
            parser.error("Source commit changed during verification")

    clean_source()
    version = subprocess.check_output(
        [str(Path(args.pg_bin) / "postgres"), "--version"], text=True
    ).strip()
    major = version.split()[2].split(".")[0]
    if major not in {"17", "18"}:
        parser.error("PostgreSQL17 or18 required")
    output = Path(".local/qa/functional-completion") / ("pg" + major)
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "tested_sha": head,
        "postgres": version,
        "python": sys.version,
        "browser_requested": args.browser,
        "stages": [],
        "status": "RUNNING",
        "started_at_epoch": time.time(),
    }
    env = {
        **os.environ,
        "FATWA_RECOVERY_PG_BIN": str(Path(args.pg_bin).resolve()),
        "FATWA_TEST_PG_BIN": str(Path(args.pg_bin).resolve()),
    }
    stages = [
        ("system", [sys.executable, "manage.py", "check"]),
        ("migrations", [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"]),
        ("recording", ["node", "--test", "apps/browser_audio/test_capture_worklet.mjs"]),
        ("offline_client", ["node", "--test", "apps/research_library/static/research_library/offline/core.test.mjs"]),
        (
            "affected",
            [sys.executable, "manage.py", "test", *LABELS, "--noinput", "--verbosity", "2"],
        ),
        (
            "recovery",
            [sys.executable, "-m", "tests.casework.functional_recovery", "--pg-bin", args.pg_bin],
        ),
    ]
    if args.browser:
        stages.append(
            (
                "browser",
                [
                    sys.executable,
                    "manage.py",
                    "test",
                    *BROWSER_LABELS,
                    "--noinput",
                    "--verbosity",
                    "2",
                ],
            )
        )
    for name, command in stages:
        path = output / (name + ".log")
        with path.open("w") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        raw = path.read_bytes()
        clean_source()
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print(raw.decode(errors="replace"), flush=True)
        receipt["stages"].append(
            {
                "name": name,
                "command": command,
                "exit_code": result.returncode,
                "log_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        receipt["status"] = "FAILED" if result.returncode else "RUNNING"
        (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if result.returncode:
            return result.returncode
    if args.browser:
        proof = json.loads(Path(".local/qa/functional-completion/browser/result.json").read_text())
        if proof.get("status") != "PASS" or proof.get("sandbox") is not True:
            raise RuntimeError("Protected browser proof missing")
    receipt["status"] = "PASS" if args.browser else "SERVICE_HTTP_RECOVERY_ONLY"
    from functional_continuation_receipt import write_continuation_receipt
    from functional_scope_receipt import write_scope_receipt

    try:
        accounting = write_scope_receipt(receipt, output, labels=LABELS)
        continuation = write_continuation_receipt(receipt, output, labels=LABELS, browser_labels=BROWSER_LABELS)
    except Exception:
        receipt["status"] = "FAILED_SCOPE_ACCOUNTING"
        (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    receipt["scope_audit_status"] = accounting["status"]
    receipt["completed_original_owner_points"] = accounting["completed_original_owner_points"]
    receipt["continuation_scope_status"] = continuation["status"]
    receipt["completed_additional_original_owner_points"] = continuation["completed_additional_original_owner_points"]
    (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (Path(".local/qa/functional-continuation") / ("pg" + major) / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
