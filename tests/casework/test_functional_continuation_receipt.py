"""Receipt rejection probes; temporary verifier inputs are not execution evidence."""

import copy
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from infra.dev import functional_continuation_receipt as receipts
from infra.dev.functional_verify import BROWSER_LABELS, LABELS

REPOSITORY = Path(__file__).resolve().parents[2]
HEAD = "1234567890abcdef1234567890abcdef12345678"


class ContinuationReceiptTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="receipt-rejection-")))
        plan = json.loads((REPOSITORY / receipts.PLAN).read_text())
        paths = {
            receipts.PLAN,
            Path(plan["source_inventory"]["path"]),
            Path(plan["source_inventory"]["specification_path"]),
            Path(plan["source_inventory"]["decision_path"]),
            Path(plan["previous_batch"]["scope_plan_path"]),
        }
        for group in plan["groups"]:
            paths.add(Path(group["contract"]))
            for name in [*group["service_test_classes"], group["browser"]["test_class"]]:
                paths.add(Path(name.rsplit(".", 1)[0].replace(".", "/") + ".py"))
        for path in paths:
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / path, folder / path)
        self.enterContext(chdir(folder))
        self.enterContext(patch.dict(os.environ, {"FATWA_BROWSER_SANDBOX": "1"}))

        def git(command, **kwargs):
            if command == ["git", "rev-parse", "HEAD"]:
                return HEAD + "\n"
            if command == ["git", "status", "--porcelain", "--untracked-files=normal"]:
                return ""
            self.fail(f"Unexpected command in pure receipt probe: {command}")

        self.enterContext(patch.object(receipts.subprocess, "check_output", side_effect=git))
        self.log_root = Path("logs")
        self.log_root.mkdir()
        self.execution = {
            "tested_sha": HEAD,
            "postgres": "postgres (PostgreSQL) 17.11",
            "started_at_epoch": time.time() - 2,
            "status": "PASS",
            "browser_requested": True,
            "stages": [],
        }
        for stage in (
            "system",
            "migrations",
            "recording",
            "recording_player",
            "offline_client",
            "affected",
            "recovery",
        ):
            self.log(stage, "verifier fixture\nRan 1 test in 0.001s\n\nOK\n")
        self.browser_log()
        tables = [*receipts.PRIOR_TABLES]
        tables.extend(name for names in receipts.NEW_WORKFLOWS.values() for name in names)
        self.recovery = {
            "tested_sha": HEAD,
            "status": "PASS",
            "postgres_major": 17,
            "source_unchanged": True,
            "source_frozen": True,
            "fresh_process_readers": True,
            "restored_private_storage_used": True,
            "restored_unchanged_after_readers": True,
            "all_restored_originals_verified_after_readers": True,
            "source_originals_unchanged": True,
            "encrypted": True,
            "plaintext_dump_present": False,
            "additional_workflows": [*receipts.PRIOR_WORKFLOWS, *receipts.NEW_WORKFLOWS],
            "tables": {name: {"rows": 1, "sha256": "d" * 64} for name in tables},
            "durable_original_references": [
                {"table": "research_library_libraryblob", "backend": "private-filesystem-v1"}
            ],
            "restored_workflow_results": {
                helper: {"fixture": True}
                for helper in (*receipts.PRIOR_WORKFLOWS, *receipts.NEW_WORKFLOWS)
            },
        }
        for helper, checks in receipts.RESTORED_DENIAL_CHECKS.items():
            self.recovery["restored_workflow_results"][helper] = {
                "denial_checks": checks.copy(),
                "denied_read_count": sum(checks.values()),
                "positive_reads_after_denial": True,
            }
        self.recovery_path = Path(".local/qa/functional-continuation/recovery-pg17.json")
        self.json(self.recovery_path, self.recovery)
        for _, path, schema in (*receipts.PRIOR_BROWSER_JOURNEYS, *receipts.NEW_BROWSER_JOURNEYS):
            if path is None:
                continue
            proof = {
                "status": "PASS",
                "sandbox": True,
                "widths": [320, 1280],
                "page_errors": [],
                "external_requests": [],
            }
            if schema == "quality":
                proof["browser_errors"] = proof.pop("page_errors")
            elif schema == "assignments":
                proof["browser_sandbox"] = proof.pop("sandbox")
            elif schema == "casework":
                proof.pop("sandbox")
                proof["views"] = [
                    {"width": width, "rtl": True, "no_overflow": True}
                    for width in proof.pop("widths")
                ]
                proof.update(tests_run=1, unsafe_url_requests=0)
            self.json(path, proof)
            directory = Path(path).parent
            for width in (320, 1280):
                (directory / f"verifier-fixture-{width}.png").write_bytes(b"verifier fixture")
            if schema not in {"assignments", "casework"}:
                with zipfile.ZipFile(directory / "trace.zip", "w") as archive:
                    archive.writestr("verifier-fixture.trace", '{"fixture": true}')

    def json(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n")

    def log(self, stage, text):
        raw = text.encode()
        (self.log_root / (stage + ".log")).write_bytes(raw)
        self.execution["stages"] = [row for row in self.execution["stages"] if row["name"] != stage]
        self.execution["stages"].append(
            {
                "name": stage,
                "exit_code": 0,
                "command": ["verifier-fixture", stage],
                "log_sha256": receipts.sha(raw),
            }
        )

    def browser_log(self, identities=None):
        if identities is None:
            identities = [
                row[0] for row in (*receipts.PRIOR_BROWSER_JOURNEYS, *receipts.NEW_BROWSER_JOURNEYS)
            ]
        lines = []
        for index, identity in enumerate(identities):
            method = identity.rsplit(".", 1)[1]
            # Real Django startup/HTTP output can interrupt the first status line.
            detail = (
                "Found 20 test(s).\nSystem check identified no issues.\nok" if index == 0 else "ok"
            )
            lines.append(f"{method} ({identity}) ... {detail}")
        self.log("browser", "\n".join(lines) + f"\nRan {len(identities)} tests in 0.001s\n\nOK\n")

    def receipt(self):
        return receipts.write_continuation_receipt(
            self.execution, self.log_root, labels=LABELS, browser_labels=BROWSER_LABELS
        )

    def test_full_inventory_records_all_prior_and_additional_evidence(self):
        result = self.receipt()
        self.assertEqual(result["protected_browser_tests"], 20)
        self.assertEqual(
            (result["prior_browser_journeys"], result["additional_browser_journeys"]), (8, 12)
        )
        self.assertEqual(
            (result["browser_json_proofs"], result["browser_log_only_proofs"]), (19, 1)
        )
        self.assertEqual(len(result["browser_proofs"]), 20)
        recovery = result["encrypted_recovery_proof"]
        self.assertEqual(recovery["total_nonempty_tables"], 47)
        self.assertEqual(
            (recovery["prior_nonempty_table_count"], recovery["new_nonempty_table_count"]), (22, 25)
        )
        self.assertEqual(len(recovery["restored_workflow_results"]), 11)
        self.assertEqual(recovery["fresh_process_denied_reads"], 37)
        self.assertEqual(result["completed_additional_original_owner_points"], 35)

    def test_missing_or_replaced_journey_cannot_pass_despite_all_json_proofs(self):
        identities = [
            row[0] for row in (*receipts.PRIOR_BROWSER_JOURNEYS, *receipts.NEW_BROWSER_JOURNEYS)
        ]
        without_audio = [identity for identity in identities if "BrowserAudioTests" not in identity]
        for observed, reason in (
            (without_audio, "Exactly 20"),
            (without_audio + ["unrelated.tests.ExampleTests.test_other"], "omitted or replaced"),
        ):
            with self.subTest(reason=reason):
                self.browser_log(observed)
                with self.assertRaisesRegex(RuntimeError, reason):
                    self.receipt()

    def test_missing_replaced_or_empty_prior_and_new_tables_cannot_pass(self):
        for name in (
            "research_workspace_researchcollectionevent",
            "material_import_roundtripreceipt",
            "canonical_search_searchdocument",
            "public_answer_media_transcriptaction",
            "precise_citations_citationanchor",
            "case_attachments_caseattachment",
        ):
            for operation in ("omit", "replace", "empty"):
                with self.subTest(name=name, operation=operation):
                    recovery = copy.deepcopy(self.recovery)
                    if operation == "empty":
                        recovery["tables"][name]["rows"] = 0
                    else:
                        previous = recovery["tables"].pop(name)
                        if operation == "replace":
                            recovery["tables"][name + "_unrelated"] = previous
                    self.json(self.recovery_path, recovery)
                    with self.assertRaisesRegex(
                        RuntimeError, "47 prior and new|empty prior or new"
                    ):
                        self.receipt()

    def test_prior_workflow_must_have_its_fresh_reader_receipt(self):
        self.recovery["additional_workflows"].remove("apps.public_knowledge.recovery_support")
        self.json(self.recovery_path, self.recovery)
        with self.assertRaisesRegex(RuntimeError, "prior or new workflow"):
            self.receipt()

    def test_missing_or_changed_fresh_process_denial_proof_cannot_pass(self):
        for helper in receipts.RESTORED_DENIAL_CHECKS:
            for operation in ("missing", "mapping", "count", "positive_read"):
                with self.subTest(helper=helper, operation=operation):
                    recovery = copy.deepcopy(self.recovery)
                    results = recovery["restored_workflow_results"]
                    if operation == "missing":
                        results.pop(helper)
                    elif operation == "mapping":
                        # Preserve the aggregate while substituting a different
                        # denial kind; exact individual trust checks are required.
                        checks = results[helper]["denial_checks"]
                        key = next(iter(checks))
                        checks["unrelated_denial"] = checks.pop(key)
                    elif operation == "count":
                        results[helper]["denied_read_count"] -= 1
                    else:
                        results[helper]["positive_reads_after_denial"] = False
                    self.json(self.recovery_path, recovery)
                    with self.assertRaisesRegex(RuntimeError, "eleven fresh-process|denial proof"):
                        self.receipt()
        recovery = copy.deepcopy(self.recovery)
        recovery["restored_workflow_results"].pop("apps.public_knowledge.recovery_support")
        self.json(self.recovery_path, recovery)
        with self.assertRaisesRegex(RuntimeError, "eleven fresh-process"):
            self.receipt()

    def test_missing_or_stale_prior_and_new_proofs_cannot_pass_all_20_tests(self):
        for path in (
            ".local/qa/case-assignments/browser/assignments.json",
            ".local/qa/v6-casework/browser/evidence.json",
            ".local/qa/functional-continuation/library-browser/result.json",
            ".local/qa/functional-continuation/citations-browser/result.json",
            ".local/qa/functional-continuation/search-recording-browser/result.json",
        ):
            for operation in ("omit", "stale"):
                with self.subTest(path=path, operation=operation):
                    artifact = Path(path)
                    raw = artifact.read_bytes()
                    if operation == "omit":
                        artifact.unlink()
                    else:
                        os.utime(artifact, (0, 0))
                    try:
                        with self.assertRaisesRegex(RuntimeError, "Missing or stale"):
                            self.receipt()
                    finally:
                        artifact.write_bytes(raw)

    def test_service_only_run_remains_pending_with_zero_browser_credit(self):
        self.execution.update(status="SERVICE_HTTP_RECOVERY_ONLY", browser_requested=False)
        self.execution["stages"] = [
            row for row in self.execution["stages"] if row["name"] != "browser"
        ]
        result = self.receipt()
        self.assertEqual(result["status"], "PENDING_PROTECTED_BROWSER")
        self.assertEqual(result["completed_additional_original_owner_points"], 0)
        self.assertEqual(result["protected_browser_tests"], 0)
        self.assertEqual(result["browser_proofs"], [])
