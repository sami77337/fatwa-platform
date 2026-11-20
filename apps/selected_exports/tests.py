"""Actual PostgreSQL, source readers, ZIP bytes, native forms and denial boundaries."""

import csv
import io
import json
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch
from urllib.parse import urlencode

from django.db import IntegrityError, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseSource
from apps.knowledge_links.tests import Authority as KnowledgeAuthority
from apps.research_workspace import services as research
from apps.research_workspace.rights import Resource
from apps.research_workspace.tests import SETTINGS as RESEARCH_SETTINGS
from apps.research_workspace.tests import ResearchFixture
from tests.casework.test_http import hidden

from . import policy, services
from .authority import ExportAuthority
from .models import ExportArtifact, ExportEvent, ExportJob

FEATURES = {
    **RESEARCH_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_SELECTED_EXPORTS_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


def post(client, path, fields, page=None):
    token = (
        hidden(page, "csrfmiddlewaretoken") if page else client.cookies["fatwa_casework_csrf"].value
    )
    return client.post(
        path,
        urlencode({"csrfmiddlewaretoken": token, **fields}, doseq=True),
        content_type="application/x-www-form-urlencoded",
    )


class FixtureExportAuthority(ExportAuthority):
    def __init__(self, ref):
        self.ref = ref
        self.denied = set()

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied)))

    def permits(self, **kw):
        resource = kw["resource"]
        kind = resource.kind if resource else ""
        return (
            kw["case_ref"] == self.ref
            and kw["provider_id"] == "synthetic-publication-directory"
            and kw["subject_id"] == "editor"
            and kw["auth_epoch"] == "epoch-1"
            and kw["action"]
            in {
                "VIEW",
                "PREPARE",
                "GENERATE",
                "DOWNLOAD",
                "MANAGE",
                "EXPORT_RECORD",
                "EXPORT_SENSITIVE",
                "EXPORT_MEDIA",
            }
            and (kw["action"], kind) not in self.denied
        )


class VersionedKnowledge(KnowledgeAuthority):
    def projection_epoch(self):
        return repr((self.ref, self.allow_open))


class ExportFixture(ResearchFixture):
    def setUp(self):
        super().setUp()
        self.export_authority = FixtureExportAuthority(self.receipt["public_ref"])
        self.authority = VersionedKnowledge(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_SELECTED_EXPORTS_AUTHORITY=self.export_authority,
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def chosen(self):
        return [self.source(2), self.source(3)]

    def transcript_resource(self):
        return Resource(**self.search(kind="TRANSCRIPT")["results"][0]["resource"])

    def prepare_export(self, **changes):
        case = Case.objects.get(pk=self.receipt["case_id"])
        selected = changes.pop("selected", None)
        arguments = dict(
            selected=self.chosen() if selected is None else selected,
            format="JSON",
            include_files=False,
            request_key=uuid.uuid4(),
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return services.prepare(**self.common, **{**arguments, **changes})

    def build(self, job):
        queued = services.command(
            **self.common,
            job_id=job["id"],
            action="QUEUE",
            request_key=uuid.uuid4(),
            expected_revision=job["revision"],
        )
        self.assertEqual(queued["state"], "QUEUED")
        return services.run_job(**self.common, job_id=job["id"], request_key=uuid.uuid4())

    def download_export(self, job):
        return services.download(**self.common, job_id=job["id"], request_key=uuid.uuid4())

    def unpack(self, raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            files = {name: bundle.read(name) for name in bundle.namelist()}
        manifest = json.loads(files["manifest.json"])
        for member in manifest["files"]:
            self.assertEqual(len(files[member["path"]]), member["bytes"])
            self.assertEqual(sha256(files[member["path"]]).hexdigest(), member["sha256"])
        self.assertEqual(set(files), {"manifest.json", *[row["path"] for row in manifest["files"]]})
        return files, manifest

    def login(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303)
        return client


@override_settings(**FEATURES)
class ExportTests(ExportFixture, TransactionTestCase):
    def test_real_selected_resources_all_formats_archive_checksums_and_no_source_mutation(self):
        before = (
            list(CaseEvent.objects.values()),
            list(AnswerRevision.objects.values()),
            list(CaseSource.objects.values()),
        )
        for format in ("JSON", "CSV", "JSONL"):
            with self.subTest(format=format):
                job = self.prepare_export(format=format)
                preview = services.preview(**self.common, job_id=job["id"])
                self.assertEqual(len(preview["preview"]), 2)
                self.assertGreater(preview["estimated_bytes"], 0)
                ready = self.build(job)
                self.assertEqual((ready["state"], ready["completed"]), ("READY", 2))
                downloaded = self.download_export(job)
                files, manifest = self.unpack(downloaded["raw"])
                self.assertEqual((manifest["requested"], manifest["included"]), (2, 2))
                self.assertEqual(len(files), 2)
                if format == "JSON":
                    records = json.loads(files["records.json"])["records"]
                elif format == "JSONL":
                    records = [json.loads(line) for line in files["records.jsonl"].splitlines()]
                else:
                    records = [
                        {k: json.loads(v) for k, v in row.items()}
                        for row in csv.DictReader(
                            io.StringIO(files["records.csv"].decode(), newline="")
                        )
                    ]
                self.assertEqual(
                    [r["identifier"] for r in records], [r.identifier for r in self.chosen()]
                )
                self.assertEqual(
                    records[0]["metadata"]["heading_title"], self.heading.title_original
                )
                self.assertIsNone(records[0]["content"])
                self.assertEqual(downloaded["raw"], self.download_export(job)["raw"])
                self.assertNotIn(self.receipt["token"].encode(), downloaded["raw"])
                for sentinel in (
                    b"PRIVATE QUESTION",
                    b"PRIVATE ANSWER",
                    b"PRIVATE NOTE",
                    b"synthetic-editor-credential",
                    b"storage_key",
                    b"auth_epoch",
                ):
                    self.assertNotIn(sentinel, downloaded["raw"])
        self.assertEqual(
            before,
            (
                list(CaseEvent.objects.values()),
                list(AnswerRevision.objects.values()),
                list(CaseSource.objects.values()),
            ),
        )

    def test_transcript_exact_text_metadata_and_distinct_sensitive_grant(self):
        selected = self.transcript_resource()
        self.export_authority.denied.add(("EXPORT_SENSITIVE", "TRANSCRIPT"))
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[selected])
        self.assertEqual(ExportJob.objects.count(), 0)
        self.export_authority.denied.clear()
        job = self.prepare_export(selected=[selected])
        self.build(job)
        files, _ = self.unpack(self.download_export(job)["raw"])
        record = json.loads(files["records.json"])["records"][0]
        self.assertEqual(record["content"]["question"]["text"], self.transcript_text)
        self.assertEqual(record["content"]["question"]["start_ms"], 0)
        self.assertEqual(record["metadata"]["source_id"], self.transcript_source_id)
        self.assertNotIn("review_note", str(record))

    def test_actual_media_opt_in_and_no_original_filename_or_hidden_files(self):
        self.with_media()
        selected = Resource(**self.search(kind="MEDIA")["results"][0]["resource"])
        self.export_authority.denied.add(("EXPORT_MEDIA", selected.kind))
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[selected], include_files=True)
        metadata_job = self.prepare_export(selected=[selected], include_files=False)
        self.build(metadata_job)
        files, manifest = self.unpack(self.download_export(metadata_job)["raw"])
        self.assertEqual(set(files), {"records.json", "manifest.json"})
        self.assertFalse(manifest["files_requested"])
        self.export_authority.denied.clear()
        job = self.prepare_export(selected=[selected], include_files=True)
        self.assertEqual(self.build(job)["state"], "READY")
        files, _ = self.unpack(self.download_export(job)["raw"])
        original = research.open_resource(**self.common, resource=selected)
        self.assertEqual(files["media/0001.wav"], original["raw"])
        self.assertNotIn(original["filename"], str(json.loads(files["manifest.json"])))

    def test_missing_requested_file_is_partial_retry_restores_exact_scope_and_old_result_denied(
        self,
    ):
        self.with_media()
        selected = Resource(**self.search(kind="MEDIA")["results"][0]["resource"])
        job = self.prepare_export(selected=[self.source(2), selected], include_files=True)
        original = research.open_resource

        def missing(**kw):
            if kw["resource"] == selected:
                raise cases.CaseConflict("private_storage_unavailable")
            return original(**kw)

        with patch.object(research, "open_resource", side_effect=missing):
            partial = self.build(job)
            self.assertEqual((partial["state"], partial["completed"]), ("PARTIAL", 1))
            files, manifest = self.unpack(self.download_export(job)["raw"])
            self.assertEqual(
                manifest["outcomes"],
                [{"ordinal": 1, "status": "INCLUDED"}, {"ordinal": 2, "status": "UNAVAILABLE"}],
            )
            self.assertEqual(set(files), {"records.json", "manifest.json"})
        # A different current outcome requires a new attempt, not silent changes
        # to the already prepared result bytes.
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        current = services.status(**self.common, job_id=job["id"])
        ready = self.build(current)
        self.assertEqual((ready["state"], ready["attempt"], ready["completed"]), ("READY", 2, 2))
        files, _ = self.unpack(self.download_export(job)["raw"])
        self.assertIn("media/0002.wav", files)
        self.assertEqual(ExportArtifact.objects.filter(job_id=job["id"]).count(), 2)

    def test_download_rechecks_file_and_all_current_permissions_not_just_stored_bytes(self):
        self.with_media()
        selected = Resource(**self.search(kind="MEDIA")["results"][0]["resource"])
        job = self.prepare_export(selected=[selected], include_files=True)
        self.build(job)
        self.rights.denied.add((selected.kind, "READ_MEDIA"))
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        self.rights.denied.clear()
        with patch.object(
            research, "open_resource", side_effect=cases.CaseConflict("private_storage_unavailable")
        ):
            with self.assertRaises(cases.CaseConflict):
                self.download_export(job)
        self.export_authority.denied.add(("DOWNLOAD", ""))
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        self.assertFalse(ExportEvent.objects.filter(action="DOWNLOAD").exists())

    def test_read_rights_do_not_grant_export_default_off_unversioned_and_changed_resource(self):
        self.assertTrue(research.open_resource(**self.common, resource=self.source(2)))
        for override in (
            {"FATWA_SELECTED_EXPORTS_ENABLED": False},
            {"FATWA_SELECTED_EXPORTS_AUTHORITY": None},
        ):
            with override_settings(**override), self.assertRaises(cases.CaseConflict):
                self.prepare_export()
        self.export_authority.denied.add(("EXPORT_RECORD", "REFERENCE"))
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export()
        self.export_authority.denied.clear()
        with (
            patch.object(self.export_authority, "projection_epoch", return_value=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.prepare_export()
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[replace(self.source(2), sha256="0" * 64)])
        self.assertEqual(ExportJob.objects.count(), 0)

    def test_prepare_idempotency_duplicate_resources_stale_case_and_concurrent_claim(self):
        key = uuid.uuid4()
        job = self.prepare_export(request_key=key)
        self.assertEqual(job["id"], self.prepare_export(request_key=key)["id"])
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(request_key=key, format="CSV")
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[self.source(2), self.source(2)])
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(expected_revision=1)
        services.command(
            **self.common,
            job_id=job["id"],
            action="QUEUE",
            request_key=uuid.uuid4(),
            expected_revision=job["revision"],
        )
        claim_key = uuid.uuid4()

        def run(_):
            connections.close_all()
            try:
                return services.run_job(**self.common, job_id=job["id"], request_key=claim_key)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual({r["state"] for r in results} - {"RUNNING", "READY"}, set())
        self.assertEqual(ExportEvent.objects.filter(action="START").count(), 1)
        self.assertEqual(ExportArtifact.objects.count(), 1)

    def test_cancel_expiry_and_stale_commands_block_retrieval_without_erasing_audit(self):
        job = self.prepare_export()
        ready = self.build(job)
        before = ExportArtifact.objects.count()
        cancelled = services.command(
            **self.common,
            job_id=job["id"],
            action="CANCEL",
            request_key=uuid.uuid4(),
            expected_revision=ready["revision"],
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        self.assertEqual(ExportArtifact.objects.count(), before)
        with override_settings(FATWA_SELECTED_EXPORTS_TTL_SECONDS=1):
            expiring = self.prepare_export()
        time.sleep(1.1)
        expired = services.status(**self.common, job_id=expiring["id"])
        self.assertEqual(expired["state"], "EXPIRED")
        with self.assertRaises(cases.CaseConflict):
            services.command(
                **self.common,
                job_id=expiring["id"],
                action="QUEUE",
                request_key=uuid.uuid4(),
                expected_revision=expired["revision"],
            )
        self.assertEqual(
            ExportEvent.objects.filter(job_id=expiring["id"], action="EXPIRE").count(), 1
        )

    def test_exact_owner_scope_cross_case_and_epoch_revocation(self):
        job = self.prepare_export()
        other = cases.intake_case(
            original_question="other private",
            source_event_id="export-other",
            requester_id="other",
            idempotency_key="export-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.status(**{**self.common, "case_id": other["case_id"]}, job_id=job["id"])
        with self.assertRaises(cases.CaseConflict):
            services.status(**{**self.common, "subject_id": "publisher"}, job_id=job["id"])
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], auth_epoch="revoked"
        )
        with self.assertRaises(cases.CaseConflict):
            services.status(**self.common, job_id=job["id"])

    def test_late_mixed_kind_export_revocation_rolls_back_whole_prepare(self):
        selected = [self.source(2), self.transcript_resource()]
        original = self.export_authority.permits

        def revoke(**kw):
            if kw["resource"] and kw["resource"].kind == "TRANSCRIPT":
                self.export_authority.denied.add(("EXPORT_RECORD", "REFERENCE"))
            return original(**kw)

        with (
            patch.object(self.export_authority, "permits", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.prepare_export(selected=selected)
        self.assertEqual((ExportJob.objects.count(), ExportEvent.objects.count()), (0, 0))

    def test_last_scope_callback_revokes_transcript_read_after_last_source_check(self):
        job = self.prepare_export(selected=[self.transcript_resource()])
        original = self.export_authority.permits
        seen = 0

        def revoke(**kw):
            nonlocal seen
            if kw["action"] == "GENERATE" and kw["resource"] is None:
                seen += 1
                # Claim has nested boundaries (four calls); build exits after
                # its final source checks. Revoke at the last inner scope exit.
                if seen == 7:
                    self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            return original(**kw)

        with patch.object(self.export_authority, "permits", side_effect=revoke):
            result = self.build(job)
        self.assertGreaterEqual(seen, 7)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(ExportArtifact.objects.count(), 0)

    def test_source_change_after_serialization_rolls_back_artifact_and_records_failure(self):
        job = self.prepare_export()
        original = services.archive

        def changed(**kw):
            result = original(**kw)
            self.rights.denied.add(("REFERENCE", "READ_METADATA"))
            return result

        with patch.object(services, "archive", side_effect=changed):
            result = self.build(job)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(ExportArtifact.objects.count(), 0)
        self.assertEqual(ExportEvent.objects.filter(action="FAIL").count(), 1)

    def test_immutable_scope_history_artifact_and_database_lifecycle_guards(self):
        job = self.prepare_export()
        source = ExportJob.objects.get(pk=job["id"])
        malformed = [{"resource": source.selection[0]["resource"], "record_sha256": None}]
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportJob.objects.create(
                case=source.case,
                provider_id=source.provider_id,
                subject_id=source.subject_id,
                request_key=uuid.uuid4(),
                case_revision=source.case_revision,
                evidence_version=source.evidence_version,
                selection=malformed,
                selection_sha256="0" * 64,
                format="JSON",
                include_files=False,
                expires_at=source.expires_at,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportJob.objects.filter(pk=job["id"]).update(format="CSV")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportEvent.objects.filter(job_id=job["id"]).update(state="READY")
        with policy.boundary(**self.common) as (_, actor):
            with self.assertRaises(IntegrityError), transaction.atomic():
                services._record(
                    ExportJob.objects.get(pk=job["id"]),
                    actor,
                    self.directory,
                    action="READY",
                    state="READY",
                    request_key=uuid.uuid4(),
                )
        self.build(job)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportArtifact.objects.filter(job_id=job["id"]).update(raw=b"changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportEvent.objects.filter(job_id=job["id"]).delete()

    def test_secret_markers_in_source_text_are_rejected_not_silently_exported(self):
        # A real authorized file, not a forged export result.
        case = Case.objects.get(pk=self.receipt["case_id"])
        attached = attachments.upload(
            token=self.receipt["token"],
            raw=b"password=synthetic-private-value",
            filename="private.txt",
            media_type="text/plain",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        selected = Resource("ATTACHMENT", attached["id"], attached["sha256"])
        with self.assertRaisesMessage(cases.CaseConflict, "export_sensitive_marker"):
            self.prepare_export(selected=[selected], include_files=True)
        self.assertEqual(ExportArtifact.objects.count(), 0)

    def test_native_http_selection_preview_queue_build_download_csrf_and_signed_scope(self):
        client = self.login()
        entry = client.get("/casework/staff/")
        self.assertEqual(entry.status_code, 200)
        desk = post(
            client,
            "/casework/staff/",
            {"action": "exports_open", "case_ref": self.receipt["public_ref"]},
        )
        self.assertEqual(desk.status_code, 200)
        desk = post(
            client,
            "/casework/staff/",
            {
                "action": "exports_search",
                "case_ref": self.receipt["public_ref"],
                "kind": "REFERENCE",
                "query": "فرع",
                "edition_id": str(self.catalog_id),
            },
        )
        self.assertEqual(desk.status_code, 200)
        fields = {
            "action": "exports_prepare",
            "case_ref": self.receipt["public_ref"],
            "state": hidden(desk, "state"),
            "selection": "0",
            "format": "JSONL",
            "include_files": "no",
        }
        self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
        bad = post(client, "/casework/staff/", {**fields, "state": fields["state"] + "tamper"})
        self.assertEqual(bad.status_code, 400)
        preview = post(client, "/casework/staff/", fields)
        self.assertEqual(preview.status_code, 200, preview.content[:200])
        job = ExportJob.objects.get()
        queued = post(
            client,
            "/casework/staff/",
            {
                "action": "exports_queue",
                "case_ref": self.receipt["public_ref"],
                "job_id": str(job.pk),
                "revision": "1",
                "request_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(queued.status_code, 200)
        built = post(
            client,
            "/casework/staff/",
            {
                "action": "exports_build",
                "case_ref": self.receipt["public_ref"],
                "job_id": str(job.pk),
                "request_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(built.status_code, 200)
        downloaded = post(
            client,
            "/casework/staff/",
            {
                "action": "exports_download",
                "case_ref": self.receipt["public_ref"],
                "job_id": str(job.pk),
                "request_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded["Content-Type"], "application/zip")
        self.assertEqual(downloaded["X-Export-SHA256"], sha256(downloaded.content).hexdigest())
        self.assertIn("no-store", downloaded["Cache-Control"])
        self.assertEqual(downloaded["X-Export-Result"], "complete")
        files, _ = self.unpack(downloaded.content)
        self.assertIn("records.jsonl", files)
        self.assertEqual(ExportEvent.objects.filter(action="DOWNLOAD").count(), 1)

    def test_native_render_late_revocation_never_returns_earlier_source(self):
        client = self.login()
        from . import views

        original = views.render

        def revoke(*args, **kw):
            result = original(*args, **kw)
            self.export_authority.denied.add(("EXPORT_RECORD", "REFERENCE"))
            return result

        with patch.object(views, "render", side_effect=revoke):
            response = post(
                client,
                "/casework/staff/",
                {
                    "action": "exports_search",
                    "case_ref": self.receipt["public_ref"],
                    "kind": "REFERENCE",
                    "query": "فرع",
                    "edition_id": str(self.catalog_id),
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(self.heading.title_original.encode(), response.content)
