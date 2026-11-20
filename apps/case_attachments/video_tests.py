"""Real decoding, PostgreSQL ownership and native guarded video upload/download."""

import tempfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import MediaValidationError, validate
from apps.private_media.video import validate_file
from tests.casework.test_http import Directory, hidden, post

from . import services
from . import tests as legacy
from .models import CaseAttachment
from .tests import new_case, staff_common, upload
from .video_fixtures import video

FEATURES = dict(
    FATWA_CASEWORK_WEB_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED=True,
    ROOT_URLCONF="config.campaign_urls",
)


@override_settings(**FEATURES)
class RequesterVideoTests(TransactionTestCase):
    client_for = legacy.AttachmentHTTPTests.client_for

    def test_restored_video_reader_checks_actual_originals_and_revoked_trust(self):
        from .video_recovery import populate, verify_restored
        with tempfile.TemporaryDirectory() as folder, override_settings(
            FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(Path(folder) / "originals", synthetic_fixtures_only=True)
        ):
            receipt = populate()
            connections.close_all()
            result = verify_restored(receipt)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["denied_read_count"], 6)

    def test_actual_decoders_preserve_webm_mp4_and_do_not_expand_audio_only_parser(self):
        for extension in ("webm", "mp4"):
            raw = video(extension)
            parsed = validate_file(raw, "original." + extension, "video/" + extension)
            self.assertEqual(parsed.raw, raw)
            self.assertEqual(parsed.sha256, sha256(raw).hexdigest())
            self.assertEqual(parsed.kind, "video")
            self.assertGreater(parsed.metadata["duration_seconds"], 0)
            with self.assertRaises(MediaValidationError):
                validate(raw, "original." + extension, "video/" + extension)
        for raw, name, media in (
            (b"broken", "wrong.webm", "video/webm"),
            (video()[:24], "short.webm", "video/webm"),
            (video(), "wrong.mp4", "video/mp4"),
            (video(), "wrong.webm", "text/html"),
            (video(), "../private.webm", "video/webm"),
            (b"x" * 192001, "large.webm", "video/webm"),
        ):
            with self.subTest(name=name, media=media), self.assertRaises(MediaValidationError):
                validate_file(raw, name, media)

    def test_video_original_restarts_exactly_and_invalidates_prior_approval(self):
        receipt = new_case()
        draft = cases.save_answer(**staff_common(receipt), text="جواب تجريبي قبل وصول الفيديو",
                                  expected_revision=1, expected_evidence_version=1)
        approved = cases.record_decision(**staff_common(receipt), answer_id=draft["answers"][0]["id"],
                                         action="APPROVE", expected_revision=2, expected_evidence_version=1)
        with tempfile.TemporaryDirectory() as folder, override_settings(
            FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(Path(folder) / "originals", synthetic_fixtures_only=True)
        ):
            result = upload(receipt, raw=video(), filename="question.webm", media_type="video/webm",
                            expected_revision=approved["revision"])
            connections.close_all()
            row = CaseAttachment.objects.get(pk=result["id"])
            self.assertIsNone(row.original)
            self.assertEqual(row.storage_backend, "private-filesystem-v1")
            self.assertEqual(row.kind, "video")
            self.assertEqual((row.evidence.version, row.event.sequence), (2, 4))
            self.assertEqual(services.staff_read(**staff_common(receipt), attachment_id=row.pk)["raw"], video())
            self.assertEqual(services.requester_read(token=receipt["token"], attachment_id=row.pk,
                                                    synthetic_fixtures_only=True)["raw"], video())
            case = Case.objects.get(pk=receipt["case_id"])
            self.assertEqual(case.stage, "UNDER_REVIEW")
            self.assertIsNone(case.approved_answer_id)
            self.assertEqual(case.answers.count(), 1)
            self.assertEqual(case.decisions.count(), 1)
            for action in (
                lambda: CaseAttachment.objects.filter(pk=row.pk).update(kind="audio"),
                lambda: CaseAttachment.objects.filter(pk=row.pk).update(original=b"changed"),
                lambda: CaseAttachment.objects.filter(pk=row.pk).delete(),
            ):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    action()
            executor = MigrationExecutor(connection)
            with self.assertRaises(DatabaseError):
                executor.migrate([("case_attachments", "0004_caseattachment_storage_backend_and_more")])
            self.assertEqual(services.staff_read(**staff_common(receipt), attachment_id=row.pk)["raw"], video())

    def test_video_opt_in_and_stale_revision_do_not_append_unaccepted_facts(self):
        receipt = new_case()
        for changes in ({"FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED": False}, {"FATWA_CASE_ATTACHMENTS_ENABLED": False}):
            with override_settings(**changes), self.assertRaises(cases.CaseConflict):
                upload(receipt, raw=video(), filename="question.webm", media_type="video/webm")
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertEqual(CaseAttachment.objects.count(), 0)
        upload(receipt, raw=video(), filename="question.webm", media_type="video/webm")
        with self.assertRaises(cases.CaseConflict):
            upload(receipt, raw=video(), filename="question.webm", media_type="video/webm")
        self.assertEqual((CaseEvidence.objects.count(), CaseAttachment.objects.count()), (2, 1))

    def test_campaign_native_upload_private_preview_exact_download_and_current_access(self):
        first, other = new_case(), new_case()
        client, page = self.client_for(first)
        fields = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), "action": "attachment_upload",
            "revision": hidden(page, "revision"), "upload_proof": hidden(page, "upload_proof"),
            "synthetic_only": "yes", "attachment": SimpleUploadedFile("question.webm", video(), "video/webm"),
        }
        response = client.post("/casework/status/", fields)
        self.assertEqual(response.status_code, 200, response.content)
        row = CaseAttachment.objects.get()
        action = {"action": "attachment_preview", "attachment_id": str(row.pk)}
        preview = post(client, "/casework/status/", action, response)
        self.assertContains(preview, '<video controls preload="metadata"')
        path = "/casework/status/attachments/" + str(row.pk) + "/"
        original = client.get(path)
        self.assertEqual(original.content, video())
        self.assertEqual(original["Content-Type"], "video/webm")
        self.assertIn("no-store", original["Cache-Control"])
        self.assertIn("sandbox", original["Content-Security-Policy"])
        self.assertEqual(client.head(path).content, b"")
        downloaded = post(client, "/casework/status/", {**action, "action": "attachment_download"}, preview)
        self.assertEqual(downloaded.content, video())
        foreign, _ = self.client_for(other)
        self.assertEqual(foreign.get(path).status_code, 404)
        directory = Directory()
        directory.grant(first["public_ref"])
        staff = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            login = staff.get("/casework/staff/login/")
            self.assertEqual(post(staff, "/casework/staff/login/", {"credential": directory.credential}, login).status_code, 303)
            staff_path = path.replace("/status/", "/staff/")
            self.assertEqual(staff.get(staff_path).content, video())
            directory.current = replace(directory.current, active=False)
            self.assertIn(staff.get(staff_path).status_code, (403, 404))
        cases.revoke_access(**staff_common(first), requester_id=Case.objects.get(pk=first["case_id"]).requester_id)
        self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(CaseAttachment.objects.count(), 1)

    def test_bad_upload_and_duplicate_file_fields_leave_original_facts_intact(self):
        receipt = new_case()
        client, page = self.client_for(receipt)
        def fields(raw):
            return {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), "action": "attachment_upload",
                "revision": hidden(page, "revision"), "upload_proof": hidden(page, "upload_proof"),
                "synthetic_only": "yes", "attachment": SimpleUploadedFile("bad.webm", raw, "video/webm"),
            }
        self.assertEqual(client.post("/casework/status/", fields(b"truncated")).status_code, 409)
        missing_csrf = fields(video())
        del missing_csrf["csrfmiddlewaretoken"]
        self.assertEqual(client.post("/casework/status/", missing_csrf).status_code, 403)
        duplicated = fields(video())
        duplicated["attachment"] = [SimpleUploadedFile("one.webm", video(), "video/webm"),
                                    SimpleUploadedFile("two.webm", video(), "video/webm")]
        self.assertEqual(client.post("/casework/status/", duplicated).status_code, 400)
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertEqual(CaseAttachment.objects.count(), 0)
