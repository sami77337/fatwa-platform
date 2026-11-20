"""Real file loss, crash/retry, worker execution, and authoritative rights ledger."""

import io
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import Case
from apps.knowledge_links import services as knowledge
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import validate
from apps.research_workspace.rights import Resource
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from apps.source_rights import services as ledger
from apps.source_rights.models import RightsAction, RightsRevision
from apps.source_rights.tests import Authority as SourceAuthority

from . import recovery_support, services
from . import tests as fixtures
from .models import ExportArtifact, ExportEvent, ExportJob


@override_settings(**fixtures.FEATURES)
class DurabilityTests(fixtures.ExportFixture, TransactionTestCase):
    def test_repeated_downloads_reserve_cancellation_and_expiry_capacity(self):
        with override_settings(FATWA_SELECTED_EXPORTS_TTL_SECONDS=20):
            job = self.prepare_export(selected=[self.source(2)])
        ready = self.build(job)
        while ready["revision"] < services.EVENT_LIMITS["DOWNLOAD"]:
            self.download_export(job)
            ready = services.status(**self.common, job_id=job["id"])
        self.assertEqual(ready["revision"], 94)
        self.assertFalse(ready["can_download"])
        self.assertFalse(ready["can_queue"])
        with self.assertRaisesMessage(cases.CaseConflict, "export_history_capacity"):
            self.download_export(job)
        cancelled = services.command(
            **self.common,
            job_id=job["id"],
            action="CANCEL",
            request_key=uuid.uuid4(),
            expected_revision=ready["revision"],
        )
        self.assertEqual((cancelled["state"], cancelled["revision"]), ("CANCELLED", 95))
        remaining = (
            ExportJob.objects.get(pk=job["id"]).expires_at - timezone.now()
        ).total_seconds()
        time.sleep(max(0, remaining) + 0.05)
        expired = services.status(**self.common, job_id=job["id"])
        self.assertEqual((expired["state"], expired["revision"]), ("EXPIRED", 96))
        self.assertEqual(services.status(**self.common, job_id=job["id"]), expired)
        self.assertEqual(ExportEvent.objects.filter(job_id=job["id"]).count(), 96)

    def test_actual_deleted_private_file_yields_partial_then_exact_retry(self):
        with tempfile.TemporaryDirectory(prefix="selected-export-files-") as temp:
            storage = FileSystemStorage(Path(temp) / "owned", synthetic_fixtures_only=True)
            original = b"Selected synthetic original only.\r\n"
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                case = Case.objects.get(pk=self.receipt["case_id"])
                row = attachments.upload(
                    token=self.receipt["token"],
                    raw=original,
                    filename="private-person-name.txt",
                    media_type="text/plain",
                    expected_revision=case.revision,
                    synthetic_fixtures_only=True,
                )
                selected = Resource("ATTACHMENT", row["id"], row["sha256"])
                job = self.prepare_export(selected=[self.source(2), selected], include_files=True)
                path = storage.root / "objects" / (row["sha256"] + ".blob")
                self.assertEqual(path.read_bytes(), original)
                path.unlink()
                result = self.build(job)
                self.assertEqual((result["state"], result["completed"]), ("PARTIAL", 1))
                files, manifest = self.unpack(self.download_export(job)["raw"])
                self.assertEqual(manifest["outcomes"][1]["status"], "UNAVAILABLE")
                self.assertNotIn("media/0002.txt", files)
                # A file never requested is not a missing requested file.
                metadata = self.prepare_export(selected=[selected], include_files=False)
                self.assertEqual(self.build(metadata)["state"], "READY")
                storage.put(validate(original, "private-person-name.txt", "text/plain"))
                current = services.status(**self.common, job_id=job["id"])
                self.assertEqual(self.build(current)["state"], "READY")
                files, _ = self.unpack(self.download_export(job)["raw"])
                self.assertEqual(files["media/0002.txt"], original)
                self.assertNotIn(b"private-person-name.txt", b"".join(files.values()))

    def test_interrupted_attempt_keeps_durable_lease_then_retry_and_stale_worker_cannot_finish(
        self,
    ):
        job = self.prepare_export()
        services.command(
            **self.common,
            job_id=job["id"],
            action="QUEUE",
            request_key=uuid.uuid4(),
            expected_revision=job["revision"],
        )
        with (
            override_settings(FATWA_SELECTED_EXPORTS_LEASE_SECONDS=1),
            patch.object(
                services, "archive", side_effect=RuntimeError("synthetic process interruption")
            ),
            self.assertRaises(RuntimeError),
        ):
            services.run_job(**self.common, job_id=job["id"], request_key=uuid.uuid4())
        running = services.status(**self.common, job_id=job["id"])
        self.assertEqual((running["state"], running["completed"]), ("RUNNING", 0))
        old_lease = ExportEvent.objects.get(job_id=job["id"], action="START").lease_id
        with self.assertRaises(cases.CaseConflict):
            services.command(
                **self.common,
                job_id=job["id"],
                action="QUEUE",
                request_key=uuid.uuid4(),
                expected_revision=running["revision"],
            )
        time.sleep(1.1)
        ready = self.build(running)
        self.assertEqual((ready["state"], ready["attempt"]), ("READY", 2))
        # Old worker completion cannot turn a later successful attempt into FAIL.
        before = ExportEvent.objects.count()
        services._failure(job["id"], old_lease, self.common)
        self.assertEqual(ExportEvent.objects.count(), before)
        self.assertEqual(ExportArtifact.objects.count(), 1)

    def test_worker_runs_existing_queued_job_without_browser_or_grant_inference(self):
        job = self.prepare_export()
        services.command(
            **self.common,
            job_id=job["id"],
            action="QUEUE",
            request_key=uuid.uuid4(),
            expected_revision=job["revision"],
        )
        output = io.StringIO()
        call_command(
            "run_selected_exports",
            case_id=str(self.receipt["case_id"]),
            job_id=job["id"],
            subject="editor",
            synthetic_fixtures_only=True,
            stdout=output,
        )
        self.assertIn("state=READY included=2 requested=2", output.getvalue())
        self.assertEqual(services.status(**self.common, job_id=job["id"])["state"], "READY")

    def test_approved_relationship_preserves_exact_source_and_needs_its_export_grant(self):
        proposed = self.propose("REFERENCE")
        self.approve(proposed)
        selected = Resource(**self.search(kind="KNOWLEDGE")["results"][0]["resource"])
        self.export_authority.denied.add(("EXPORT_RECORD", "REFERENCE"))
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[selected])
        self.export_authority.denied.clear()
        job = self.prepare_export(selected=[selected])
        self.assertEqual(self.build(job)["state"], "READY")
        _, manifest = self.unpack(self.download_export(job)["raw"])
        relation = manifest["materials"][0]["relationships"][0]
        self.assertEqual(relation["identifier"], self.source(2).identifier)
        self.assertEqual(relation["version_sha256"], self.source(2).sha256)
        knowledge.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=proposed["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)

    def test_nonempty_recovery_helper_uses_distinct_case_and_requires_current_grants(self):
        pins = recovery_support.populate()
        self.assertNotEqual(pins["case_id"], str(self.receipt["case_id"]))
        self.assertTrue(ExportJob.objects.filter(pk=pins["job_id"]).exists())
        self.assertTrue(ExportEvent.objects.filter(job_id=pins["job_id"]).exists())
        self.assertTrue(ExportArtifact.objects.filter(job_id=pins["job_id"]).exists())
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["artifact_sha256"], pins["sha256"])
        # This verifies the helper locally; the integration owner's encrypted
        # fresh-database/fresh-process drill supplies actual recovery evidence.


@override_settings(**fixtures.FEATURES, FATWA_SOURCE_RIGHTS_ENABLED=True)
class RightsLedgerTests(fixtures.ExportFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        overlay = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=SourceAuthority(self.receipt["public_ref"]),
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        registered = ledger.register(**self.common, kind="TOC_METADATA", target_id=self.heading.pk)
        self.grant = ledger.propose(
            **self.common,
            source_id=registered["id"],
            expected_number=0,
            uses=["READ"],
            basis="Synthetic explicit source basis",
            note="Human review",
            ttl_minutes=1,
        )
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.grant["id"],
            action="APPROVE",
            confirmed=True,
            note="Independent review",
        )

    def test_ledger_read_and_export_are_independent_and_expiry_blocks_download(self):
        selected = self.source(2)
        self.export_authority.denied.add(("EXPORT_RECORD", "REFERENCE"))
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[selected])
        self.export_authority.denied.clear()
        job = self.prepare_export(selected=[selected])
        self.assertEqual(self.build(job)["state"], "READY")
        self.assertEqual(RightsRevision.objects.get(pk=self.grant["id"]).uses, ["READ"])
        future = timezone.now() + timedelta(minutes=2)
        with (
            patch.object(ledger, "timezone", SimpleNamespace(now=lambda: future)),
            self.assertRaises(cases.CaseConflict),
        ):
            self.download_export(job)
        self.assertFalse(ExportEvent.objects.filter(action="DOWNLOAD").exists())

    def test_late_actual_ledger_revocation_rolls_back_result_and_nested_rights_write(self):
        job = self.prepare_export(selected=[self.source(2)])
        original = services.archive

        def revoke(**kw):
            result = original(**kw)
            RightsAction.objects.create(
                revision_id=self.grant["id"],
                action="REVOKE",
                subject_id="publisher",
                provider_id=self.directory.provider_id,
                auth_epoch="epoch-1",
                note="Late synthetic revocation",
            )
            return result

        with patch.object(services, "archive", side_effect=revoke):
            result = self.build(job)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(ExportArtifact.objects.count(), 0)
        self.assertFalse(RightsAction.objects.filter(action="REVOKE").exists())
