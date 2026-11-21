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
    "tests.casework.test_editor_profile_compatibility",
    "tests.casework.test_session_deadline",
    "tests.casework.test_campaign.CampaignProfileTests",
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
    "apps.pilot_workbench.tests",
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
    "apps.canonical_search.tests",
    "apps.canonical_search.test_http",
    "apps.canonical_search.test_taxonomy",
    "apps.canonical_search.test_rights",
    "apps.canonical_search.test_recovery",
    "apps.canonical_search.test_recordings",
    "apps.canonical_search.test_matches",
    "apps.canonical_search.test_match_http",
    "apps.canonical_search.test_match_recovery",
    "apps.public_answer_media.tests",
    "apps.public_answer_media.test_http",
    "apps.public_answer_media.test_recovery",
    "apps.public_answer_media.test_citation_integration",
    "apps.precise_citations.tests",
    "apps.precise_citations.test_http",
    "apps.precise_citations.test_sources",
    "apps.precise_citations.test_recovery",
    "apps.case_attachments.tests",
    "apps.case_attachments.media_tests",
    "apps.case_attachments.video_tests",
    "apps.staff_shell.tests",
    "apps.answer_media.test_youtube",
    "apps.answer_media.test_youtube_recovery",
    "apps.answer_media.test_related",
    "apps.identity_registry.tests",
    "apps.identity_registry.test_http",
    "apps.identity_registry.test_recovery",
    "apps.public_reader_tools.tests",
    "apps.public_reader_tools.test_recovery",
    "apps.material_api.tests",
    "apps.material_api.test_recovery",
    "apps.publication_schedules.tests",
    "apps.publication_schedules.test_recovery",
    "apps.publication_destinations.tests",
    "apps.publication_destinations.test_navigation",
    "apps.publication_destinations.test_recovery",
    "apps.composite_delivery.test_selection",
    "apps.composite_delivery.test_selection_recovery",
    "apps.development_taxonomy.tests",
    "apps.development_taxonomy.test_http",
    "apps.development_taxonomy.test_recovery",
    "apps.canonical_search.test_governance",
    "apps.canonical_search.test_governance_http",
    "apps.canonical_search.test_governance_recovery",
    "apps.public_teaching.tests",
    "apps.public_teaching.test_http",
    "apps.public_teaching.test_recovery",
    "apps.answer_media.tests",
    "apps.answer_media.tests_storage",
    "apps.composite_delivery.tests",
    "apps.composite_delivery.test_desk",
    "apps.composite_delivery.test_retry",
    "apps.composite_delivery.test_retry_recovery",
    "apps.case_lifecycle.test_retry",
    "apps.library_preview.test_references",
    "apps.library_preview.test_reference_recovery",
    "apps.operational_workspace.tests",
    "apps.operational_workspace.test_http",
    "apps.operational_workspace.test_recovery",
    "apps.operational_workspace.test_retry",
    "apps.operational_workspace.test_notes",
    "apps.operational_workspace.test_notes_recovery",
    "tests.casework.test_delivery",
    "apps.arabic_search_eval.test_benchmark",
    "apps.arabic_search_eval.test_benchmark_http",
    "apps.arabic_search_eval.test_benchmark_recovery",
    "apps.composite_delivery.test_publication_proposal",
    "apps.arabic_search_eval.test_review",
    "apps.arabic_search_eval.test_ranking",
    "apps.arabic_search_eval.test_services",
    "apps.arabic_search_eval.test_v14_batch",
    "apps.operational_workspace.test_metadata",
    "apps.operational_workspace.test_metadata_recovery",
    "apps.operational_workspace.test_lesson_links",
    "apps.operational_workspace.test_lesson_recovery",
    "apps.case_assignments.test_coordination",
    "apps.operational_workspace.test_coordination",
    "apps.operational_workspace.test_coordination_recovery",
    "apps.ai_gateway.tests",
    "apps.ai_gateway.test_http",
    "apps.ai_gateway.test_campaign",
    "apps.ai_gateway.test_recovery",
    "apps.private_media.test_signed_links",
    "apps.private_media.test_signed_citation_links",
    "apps.private_media.test_signed_entrypoints",
    "apps.private_media.test_link_recovery",
    "apps.operational_workspace.test_transcripts",
    "apps.operational_workspace.test_transcript_sources",
    "apps.operational_workspace.test_transcript_recovery",
    "apps.operational_workspace.test_publication",
    "apps.operational_workspace.test_publication_sources",
    "apps.operational_workspace.test_publication_recovery",
    "apps.staff_sessions.tests",
    "apps.staff_sessions.test_recovery",
    "apps.staff_sessions.test_campaign",
    "apps.data_privacy.test_campaign",
    "apps.data_privacy.test_catalog",
    "apps.data_privacy.test_citation_hooks",
    "apps.data_privacy.test_delivery_hooks",
    "apps.data_privacy.test_ledger",
    "apps.data_privacy.test_management",
    "apps.data_privacy.test_material_hooks",
    "apps.data_privacy.test_operational_hooks",
    "apps.data_privacy.test_private_hooks",
    "apps.data_privacy.test_public_derivatives",
    "apps.data_privacy.test_reader_exports",
    "apps.data_privacy.test_recovery",
    "apps.data_privacy.test_scholarly_hooks",
    "apps.data_privacy.test_source_hooks",
    "apps.data_privacy.test_source_purpose",
    "apps.ai_gateway.privacy_tests",
    "apps.ai_gateway.privacy_http_tests",
    "apps.data_quality.privacy_tests",
    "apps.team_updates.privacy_tests",
    "apps.identity_registry.privacy_tests",
    "tests.casework.test_v11_rights_boundaries",
    "apps.data_privacy.test_publication_plans",
    "apps.data_privacy.test_private_work",
    "apps.data_privacy.test_public_discovery",
    "apps.data_privacy.test_workspace_search",
    "apps.data_privacy.test_workspace_overview",
    "apps.permission_sets.test_http",
    "apps.permission_sets.test_recovery",
    "apps.permission_sets.tests",
    "apps.upload_security.test_acceptance",
    "apps.upload_security.test_admission",
    "apps.upload_security.test_clamav",
    "apps.upload_security.test_entrypoints",
    "apps.upload_security.test_http",
    "apps.upload_security.test_ledger",
    "apps.upload_security.test_privacy",
    "apps.upload_security.test_recovery",
    "apps.upload_security.test_transcripts",
    "apps.staff_mfa.test_campaign",
    "apps.staff_mfa.test_downgrade",
    "apps.staff_mfa.test_primitives",
    "apps.staff_mfa.test_recovery",
    "apps.staff_mfa.tests",
    "apps.record_suppression.test_http",
    "apps.record_suppression.test_readers",
    "apps.record_suppression.test_recovery",
    "apps.record_suppression.test_sessions",
    "apps.record_suppression.tests",
    "apps.media_derivatives.test_deadlines",
    "apps.media_derivatives.test_execution",
    "apps.media_derivatives.test_existing_sources",
    "apps.media_derivatives.test_http",
    "apps.media_derivatives.test_jobs",
    "apps.media_derivatives.test_mfa",
    "apps.media_derivatives.test_privacy",
    "apps.media_derivatives.test_recovery",
    "apps.derived_maintenance.test_callback_order",
    "apps.derived_maintenance.test_http",
    "apps.derived_maintenance.test_integrity",
    "apps.derived_maintenance.test_owner_responses",
    "apps.derived_maintenance.test_recovery",
    "apps.derived_maintenance.test_sessions",
    "apps.derived_maintenance.test_sources",
    "apps.derived_maintenance.tests",
]

BROWSER_LABELS = [
    "apps.research_library.offline_browser_tests",
    "tests.casework.test_functional_completion_browser",
    "apps.case_assignments.browser_tests",
    "apps.browser_audio.test_browser.BrowserAudioTests.test_pause_resume_preserves_one_recording_and_excludes_paused_time",
    "apps.scholarly_links.browser_tests",
    "apps.public_knowledge.browser_tests",
    "apps.selected_exports.browser_tests",
    "apps.data_quality.browser_tests",
    "apps.research_library.browser_tests",
    "apps.material_import.browser_tests",
    "apps.public_collections.browser_tests",
    "apps.case_lifecycle.browser_tests",
    "apps.canonical_search.browser_tests",
    "apps.canonical_search.browser_recordings",
    "apps.canonical_search.browser_matches",
    "apps.public_answer_media.browser_tests",
    "apps.precise_citations.browser_tests",
    "apps.case_attachments.video_browser_tests",
    "apps.staff_shell.browser_tests",
    "apps.answer_media.browser_youtube",
    "apps.answer_media.browser_related",
    "apps.identity_registry.browser_tests",
    "apps.public_reader_tools.browser_tests",
    "apps.material_api.browser_tests",
    "apps.publication_schedules.browser_tests",
    "apps.publication_destinations.browser_tests",
    "apps.composite_delivery.browser_selection",
    "apps.development_taxonomy.browser_tests",
    "apps.canonical_search.browser_governance",
    "apps.public_teaching.browser_tests",
    "apps.composite_delivery.browser_retry",
    "apps.library_preview.browser_references",
    "apps.operational_workspace.browser_tests",
    "apps.operational_workspace.browser_notes",
    "apps.arabic_search_eval.browser_benchmark",
    "apps.operational_workspace.browser_metadata",
    "apps.operational_workspace.browser_lessons",
    "apps.operational_workspace.browser_coordination",
    "apps.ai_gateway.browser_tests",
    "apps.private_media.browser_tests",
    "apps.operational_workspace.browser_transcripts",
    "apps.operational_workspace.browser_publication",
    "apps.staff_sessions.browser_tests",
    "apps.data_privacy.browser_tests",
    "apps.data_privacy.browser_work",
    "apps.permission_sets.browser_tests",
    "apps.upload_security.browser_tests",
    "apps.staff_mfa.browser_tests",
    "apps.record_suppression.browser_tests",
    "apps.media_derivatives.browser_tests",
    "apps.derived_maintenance.browser_tests",
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
        ("recording_player", ["node", "--test", "apps/public_answer_media/test_player.mjs"]),
        (
            "offline_client",
            [
                "node",
                "--test",
                "apps/research_library/static/research_library/offline/core.test.mjs",
            ],
        ),
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
        # Surface native browser failures before the longer service/recovery
        # stages. Completion still requires every unchanged mandatory stage.
        stages.insert(
            next(index for index, (name, _) in enumerate(stages) if name == "affected"),
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
            ),
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
        continuation = write_continuation_receipt(
            receipt, output, labels=LABELS, browser_labels=BROWSER_LABELS
        )
    except Exception:
        receipt["status"] = "FAILED_SCOPE_ACCOUNTING"
        (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    receipt["scope_audit_status"] = accounting["status"]
    receipt["completed_original_owner_points"] = accounting["completed_original_owner_points"]
    receipt["continuation_scope_status"] = continuation["status"]
    receipt["completed_additional_original_owner_points"] = continuation[
        "completed_additional_original_owner_points"
    ]
    (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (Path(".local/qa/functional-continuation") / ("pg" + major) / "execution.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
