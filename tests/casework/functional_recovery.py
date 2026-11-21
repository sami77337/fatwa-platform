"""Encrypted restore of nonempty new feature tables, followed by fresh-process readers."""

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import django

ADDITIONAL_WORKFLOWS = (
    "apps.scholarly_links.recovery_support",
    "apps.public_knowledge.recovery_support",
    "apps.selected_exports.recovery_support",
    "apps.research_library.recovery_support",
    "apps.material_import.recovery_support",
    "apps.public_collections.recovery_support",
    "apps.case_lifecycle.recovery_support",
    "apps.canonical_search.recovery_support",
    "apps.canonical_search.match_recovery_support",
    "apps.public_answer_media.recovery_support",
    "apps.precise_citations.recovery_support",
    "apps.case_attachments.video_recovery",
    "apps.answer_media.youtube_recovery_support",
    "apps.identity_registry.recovery_support",
    "apps.public_reader_tools.recovery_support",
    "apps.material_api.recovery_support",
    "apps.publication_schedules.recovery_support",
    "apps.publication_destinations.recovery_support",
    "apps.operational_workspace.notes_recovery_support",
    "apps.composite_delivery.selection_recovery",
    "apps.development_taxonomy.recovery_support",
    "apps.canonical_search.governance_recovery_support",
    "apps.public_teaching.recovery_support",
    "apps.composite_delivery.retry_recovery",
    "apps.library_preview.reference_recovery",
    "apps.operational_workspace.recovery_support",
    "apps.arabic_search_eval.benchmark_recovery_support",
    "apps.operational_workspace.metadata_recovery_support",
    "apps.operational_workspace.lesson_recovery_support",
    "apps.operational_workspace.coordination_recovery_support",
    "apps.ai_gateway.recovery_support",
    "apps.private_media.recovery_support",
    "apps.operational_workspace.transcript_recovery_support",
    "apps.operational_workspace.publication_recovery_support",
    "apps.staff_sessions.recovery_support",
)


def restored(fixture):
    from django.db import IntegrityError, transaction
    from django.test import override_settings

    from apps.case_assignments import services as assignments
    from apps.case_assignments.models import AssignmentEvent
    from apps.case_organization import services as organization
    from apps.case_organization.models import OrganizationRevision
    from apps.casework import services as cases
    from apps.content_reports import services as reports
    from apps.content_reports.tests import FixtureAuthority
    from apps.experimental_publication.tests import Directory
    from apps.research_workspace import collections
    from apps.research_workspace.tests import SyntheticRights

    directory = Directory([fixture["public_ref"]])
    common = dict(
        case_id=fixture["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    with override_settings(
        FATWA_CASE_ASSIGNMENTS_ENABLED=True,
        FATWA_CASE_ORGANIZATION_ENABLED=True,
        FATWA_RESEARCH_WORKSPACE_ENABLED=True,
        FATWA_RESEARCH_COLLECTIONS_ENABLED=True,
        FATWA_CASE_CITATIONS_ENABLED=True,
        FATWA_CONTENT_REPORTS_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_RESEARCH_WORKSPACE_RIGHTS=SyntheticRights(fixture["public_ref"]),
        FATWA_CONTENT_REPORTS_AUTHORITY=FixtureAuthority(
            fixture["public_ref"], directory.provider_id, "editor"
        ),
    ):
        assert assignments.read_assignment(**common)["primary_subject"] == "editor"
        assert organization.snapshot(**common)["tags"] == ["وسم اصطناعي"]
        saved = collections.read_collection(**common, collection_id=fixture["collection_id"])
        assert saved["items"][0]["available"] is True
        assert saved["items"][0]["note"] == "ملاحظة بحث خاصة"
        assert len(saved["searches"]) == 1
        assert reports.staff_desk(**common)["reports"][0]["state"] == "RESOLVED"
        for model in (AssignmentEvent, OrganizationRevision):
            try:
                with transaction.atomic():
                    model.objects.all().delete()
                raise AssertionError("Restored immutable history accepted deletion")
            except IntegrityError:
                pass
        directory.identities.pop("editor")
        for reader in (
            lambda: assignments.read_assignment(**common),
            lambda: organization.snapshot(**common),
            lambda: collections.read_collection(**common, collection_id=fixture["collection_id"]),
            lambda: reports.staff_desk(**common),
        ):
            try:
                reader()
                raise AssertionError("Restore must not fabricate identity authority")
            except cases.CaseConflict:
                pass
    for name in ADDITIONAL_WORKFLOWS:
        result = importlib.import_module(name).verify_restored(
            fixture["additional_workflows"][name]
        )
        print(json.dumps({"verified_restored_workflow": name, "result": result}, default=str))
    from apps.platform_recovery import service
    from apps.private_media.storage import configured_storage

    # The fresh process must still use the target originals after every reader.
    storage = configured_storage()
    assert storage.root == Path(fixture["private_root"])
    with service.connect() as db:
        current_references = service.references(db)
        assert current_references == fixture["expected_durable_original_references"]
    for reference in current_references:
        if reference["backend"] == "private-filesystem-v1":
            storage.get(service.original(reference))
    print("RESTORED_NEW_WORKFLOWS_PASS")


def drill(pg_bin):
    from django.test import override_settings

    from apps.answer_media import services as media
    from apps.case_assignments import services as assignments
    from apps.case_organization import services as organization
    from apps.casework import services as cases
    from apps.content_reports import services as reports
    from apps.content_reports.tests import FixtureAuthority
    from apps.platform_recovery import encrypted, maintenance, service
    from apps.private_media.filesystem import FileSystemStorage
    from apps.research_workspace import collections
    from apps.research_workspace.tests import SETTINGS, ResearchFixture

    class Fixture(ResearchFixture, unittest.TestCase):
        pass

    with (
        tempfile.TemporaryDirectory(prefix="functional-recovery-") as raw_root,
        tempfile.TemporaryDirectory(prefix="functional-keys-") as raw_keys,
    ):
        root = Path(raw_root)
        storage = FileSystemStorage(root / "source", synthetic_fixtures_only=True)
        with override_settings(
            **{
                **SETTINGS,
                "FATWA_CASE_ASSIGNMENTS_ENABLED": True,
                "FATWA_CASE_ORGANIZATION_ENABLED": True,
                "FATWA_RESEARCH_COLLECTIONS_ENABLED": True,
                "FATWA_CONTENT_REPORTS_ENABLED": True,
                "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
                "FATWA_REQUESTER_PORTAL_ENABLED": True,
                "FATWA_PRIVATE_MEDIA_STORAGE": storage,
            }
        ):
            fixture = Fixture()
            try:
                fixture.setUp()
                common = fixture.common
                fixture.with_media()
                current = cases.read_case(**common)
                cases.record_decision(
                    **common,
                    action="APPROVE",
                    answer_id=current["answers"][-1]["id"],
                    expected_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                )
                current = media.staff_snapshot(**common)
                media.release_private(
                    **common,
                    expected_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                    manifest_sha256=current["latest_package"]["sha256"],
                    confirmed=True,
                )
                pins = dict(
                    expected_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                )
                assignments.change_assignment(
                    **common, **pins, action="CLAIM", expected_assignment_version=0
                )
                organization.save(
                    **common,
                    **pins,
                    expected_metadata_version=0,
                    tags=["وسم اصطناعي"],
                    question_types=["EDUCATION"],
                    note="ملاحظة تنظيمية خاصة",
                    command_id=str(uuid.uuid4()),
                )
                cpins = dict(
                    expected_case_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                )
                collection = collections.create_collection(
                    **common, **cpins, title="مجموعة قابلة للاستعادة"
                )
                collection = collections.change_collection(
                    **common,
                    **cpins,
                    collection_id=collection["id"],
                    expected_revision=collection["collection_revision"],
                    action="ADD",
                    resource=fixture.source(2),
                    note="ملاحظة بحث خاصة",
                )
                collection = collections.change_collection(
                    **common,
                    **cpins,
                    collection_id=collection["id"],
                    expected_revision=collection["collection_revision"],
                    action="SAVE_SEARCH",
                    title="بحث محفوظ",
                    filters=dict(
                        query="فرع",
                        kind="REFERENCE",
                        edition_id=fixture.catalog_id,
                        printed_part="",
                        printed_page=None,
                    ),
                )
                with override_settings(
                    FATWA_CONTENT_REPORTS_AUTHORITY=FixtureAuthority(
                        fixture.receipt["public_ref"], fixture.directory.provider_id, "editor"
                    )
                ):
                    target = reports.requester_context(
                        token=fixture.receipt["token"],
                        expected_revision=current["revision"],
                        synthetic_fixtures_only=True,
                    )["targets"][0]["key"]
                    report = reports.submit_requester(
                        token=fixture.receipt["token"],
                        expected_revision=current["revision"],
                        selected_target=target,
                        request_key=str(uuid.uuid4()),
                        reason="BROKEN_LINK",
                        description="بلاغ استعادة اصطناعي",
                        synthetic_fixtures_only=True,
                    )
                    for action in ("START", "RESOLVE"):
                        report = reports.advance(
                            **common,
                            report_id=report["id"],
                            expected_revision=report["revision"],
                            request_key=str(uuid.uuid4()),
                            action=action,
                            action_note="إجراء بشري موثق",
                            verification_note="تحقق اصطناعي" if action == "RESOLVE" else "",
                        )
                additional = {
                    name: importlib.import_module(name).populate() for name in ADDITIONAL_WORKFLOWS
                }
                control = root / "control"
                control.mkdir(mode=0o700)
                maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
                assert (
                    maintenance.enter(root=control, synthetic_fixtures_only=True)["phase"]
                    == "FROZEN"
                )
                key = Path(raw_keys) / "backup.key"
                encrypted.generate_key(path=key, synthetic_fixtures_only=True)
                with service.connect() as db:
                    before = service.baseline(db)
                    references = service.references(db)
                    postgres_major = db.info.server_version // 10000
                tables = [
                    "case_assignments_assignmentevent",
                    "case_organization_organizationrevision",
                    "content_reports_contentreport",
                    "content_reports_reportevent",
                    "research_workspace_researchcollection",
                    "research_workspace_researchitem",
                    "research_workspace_savedresearchsearch",
                    "research_workspace_researchcollectionevent",
                ]
                for name in ADDITIONAL_WORKFLOWS:
                    tables.extend(importlib.import_module(name).TABLES)
                assert len(tables) == len(set(tables))
                assert all(before["tables"][name]["rows"] > 0 for name in tables)
                sealed = encrypted.snapshot(
                    scratch=root,
                    storage=storage,
                    pg_bin=pg_bin,
                    key_file=key,
                    maintenance_root=control,
                    synthetic_fixtures_only=True,
                )
                result = encrypted.restore(
                    bundle=sealed["bundle"],
                    expected_ciphertext_sha256=sealed["ciphertext_sha256"],
                    key_file=key,
                    scratch=root,
                    pg_bin=pg_bin,
                    synthetic_fixtures_only=True,
                )
                with service.connect(result["database"]) as db:
                    assert service.baseline(db) == before
                with service.connect() as db:
                    assert service.baseline(db) == before
                assert maintenance.status(root=control)["phase"] == "FROZEN"
                child = subprocess.run(
                    [sys.executable, "-m", "tests.casework.functional_recovery", "--restored"],
                    input=json.dumps(
                        {
                            **fixture.receipt,
                            "collection_id": collection["id"],
                            "additional_workflows": additional,
                            "private_root": result["private_root"],
                            "expected_durable_original_references": references,
                        }
                    ),
                    text=True,
                    capture_output=True,
                    env={
                        **os.environ,
                        "PGDATABASE": result["database"],
                        "PGTESTDATABASE": "test_" + result["database"],
                    },
                )
                if child.returncode:
                    raise AssertionError(child.stdout + child.stderr)
                assert "RESTORED_NEW_WORKFLOWS_PASS" in child.stdout
                restored_results = {}
                for line in child.stdout.splitlines():
                    try:
                        observed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        not isinstance(observed, dict)
                        or "verified_restored_workflow" not in observed
                    ):
                        continue
                    name = observed["verified_restored_workflow"]
                    assert name in ADDITIONAL_WORKFLOWS and name not in restored_results
                    assert isinstance(observed.get("result"), dict)
                    restored_results[name] = observed["result"]
                assert set(restored_results) == set(ADDITIONAL_WORKFLOWS)
                from infra.dev.functional_continuation_receipt import RESTORED_DENIAL_CHECKS

                for name, checks in RESTORED_DENIAL_CHECKS.items():
                    observed = restored_results[name]
                    assert observed["denial_checks"] == checks
                    assert observed["denied_read_count"] == sum(checks.values())
                    assert observed["positive_reads_after_denial"] is True
                with service.connect(result["database"]) as db:
                    assert service.baseline(db) == before
                    assert service.references(db) == references
                with service.connect() as db:
                    assert service.baseline(db) == before
                    assert service.references(db) == references
                for reference in references:
                    if reference["backend"] == "private-filesystem-v1":
                        storage.get(service.original(reference))
                assert maintenance.status(root=control)["phase"] == "FROZEN"
                receipt = {
                    "status": "PASS",
                    "tested_sha": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], text=True
                    ).strip(),
                    "postgres_major": postgres_major,
                    "tables": {name: before["tables"][name] for name in tables},
                    "durable_original_references": references,
                    "source_unchanged": True,
                    "source_frozen": True,
                    "fresh_process_readers": True,
                    "restored_private_storage_used": True,
                    "restored_unchanged_after_readers": True,
                    "all_restored_originals_verified_after_readers": True,
                    "source_originals_unchanged": True,
                    "additional_workflows": list(additional),
                    "restored_workflow_results": restored_results,
                    "encrypted": True,
                    "plaintext_dump_present": bool(list(root.rglob("database.dump"))),
                }
                assert receipt["plaintext_dump_present"] is False
                proof = (
                    Path(".local/qa/functional-continuation") / f"recovery-pg{postgres_major}.json"
                )
                proof.parent.mkdir(parents=True, exist_ok=True)
                proof.write_text(json.dumps(receipt, indent=2) + "\n")
                print(json.dumps(receipt, indent=2))
            finally:
                fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin")
    parser.add_argument("--restored", action="store_true")
    args = parser.parse_args()
    django.setup()
    if args.restored:
        from django.test import override_settings

        from apps.private_media.filesystem import FileSystemStorage

        fixture = json.load(sys.stdin)
        with override_settings(
            FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(
                fixture["private_root"], synthetic_fixtures_only=True
            )
        ):
            restored(fixture)
    else:
        if not args.pg_bin:
            parser.error("--pg-bin required for recovery drill")
        drill(args.pg_bin)


if __name__ == "__main__":
    main()
