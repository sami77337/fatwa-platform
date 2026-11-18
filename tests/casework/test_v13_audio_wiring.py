"""Shared native recording form composition; no real microphone or external send."""

import re
import tempfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings

from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework.models import Case, CaseEvidence, CaseSource
from apps.casework_web.guard import private
from apps.casework_web.requester_intake import submit_intake
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import MaintenanceUnavailable
from apps.private_media.filesystem import FileSystemStorage
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

TEMPLATES = deepcopy(settings.TEMPLATES)
TEMPLATES[0]["DIRS"].append(Path(__file__).resolve().parents[2] / "apps/browser_audio/templates")
if "apps.browser_audio.context.capture" not in TEMPLATES[0]["OPTIONS"]["context_processors"]:
    TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.browser_audio.context.capture")
AUDIO_SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "TEMPLATES": TEMPLATES,
    "FATWA_BROWSER_AUDIO_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
    "FATWA_RECOVERY_MAINTENANCE_REQUIRED": False,
    "MIDDLEWARE": ["apps.platform_recovery.middleware.MaintenanceGuard", *WEB_SETTINGS["MIDDLEWARE"]],
}


@override_settings(**AUDIO_SETTINGS)
class InitialAudioTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v13-native-audio-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        self.control = self.root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(root=self.control, storage=self.storage, synthetic_fixtures_only=True)
        config = override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
        )
        config.enable()
        self.addCleanup(config.disable)
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.page = self.client.get("/casework/")
        self.assertEqual(self.page.status_code, 200, self.page.content)
        self.fields = {
            "question": "  سؤال اصطناعي بصوت مرفق\nيُحفظ حرفيًا  ",
            "request_id": hidden(self.page, "request_id"),
            "confirmation": hidden(self.page, "confirmation"),
            "csrfmiddlewaretoken": hidden(self.page, "csrfmiddlewaretoken"),
            "synthetic_only": "yes",
        }

    def upload(self, **changes):
        media = audio_fixture()
        fields = {**self.fields, "attachment": SimpleUploadedFile(
            media["filename"], media["raw"], content_type=media["media_type"]
        ), **changes}
        return self.client.post("/casework/", fields)

    def test_one_native_case_private_original_and_exact_replay_no_second_upload(self):
        self.assertContains(self.page, 'data-input-name="attachment"')
        self.assertIn("script-src 'self'", self.page["Content-Security-Policy"])
        self.assertEqual(self.page["Permissions-Policy"], "microphone=(self), camera=()")
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.content)
        token = re.search(r'id="issued-token">([^<]+)', response.content.decode()).group(1)
        case = Case.objects.get()
        row = CaseAttachment.objects.get()
        self.assertEqual(CaseSource.objects.get().original_question, self.fields["question"])
        self.assertEqual(case.evidence_version, 2)
        self.assertEqual(CaseEvidence.objects.count(), 2)
        self.assertEqual(row.case_id, case.pk)
        self.assertIsNone(row.original)
        self.assertEqual(row.storage_backend, "private-filesystem-v1")
        self.assertEqual(row.sha256, sha256(audio_fixture()["raw"]).hexdigest())
        self.assertEqual(attachments.requester_read(
            token=token, attachment_id=str(row.pk), synthetic_fixtures_only=True
        )["raw"], audio_fixture()["raw"])
        replay = self.upload()
        self.assertEqual(replay.status_code, 200)
        self.assertNotContains(replay, token)
        self.assertEqual((Case.objects.count(), CaseAttachment.objects.count()), (1, 1))
        self.assertNotIn("script-src", response["Content-Security-Policy"])
        other = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.assertEqual(other.get(f"/casework/status/attachments/{row.pk}/").status_code, 404)
        own = self.client.get(f"/casework/status/attachments/{row.pk}/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.content, audio_fixture()["raw"])
        self.assertIn("sandbox", own["Content-Security-Policy"])
        self.assertNotIn("script-src", own["Content-Security-Policy"])

    def test_existing_requester_and_mufti_forms_render_scoped_recorders(self):
        self.assertEqual(self.upload().status_code, 200)
        portal = self.client.get("/casework/status/")
        self.assertContains(portal, 'data-input-name="attachment"')
        self.assertContains(portal, 'data-input-name="reply_attachment"')
        directory = Directory()
        directory.grant(Case.objects.get().public_ref)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory, FATWA_ANSWER_MEDIA_ENABLED=True):
            page = self.client.get("/casework/staff/login/")
            login = post(self.client, "/casework/staff/login/", {"credential": directory.credential}, page)
            self.assertEqual(login.status_code, 303)
            page = self.client.get("/casework/staff/")
            answer = post(self.client, "/casework/staff/", {
                "action": "answer_media", "case_ref": Case.objects.get().public_ref,
            }, page)
            self.assertContains(answer, 'data-input-name="answer_file"')
            self.assertIn("worker-src 'self'", answer["Content-Security-Policy"])
            self.assertEqual(answer["Permissions-Policy"], "microphone=(self), camera=()")

    def test_changed_or_omitted_initial_attachment_cannot_reuse_request_id(self):
        self.assertEqual(self.upload().status_code, 200)
        changed = SimpleUploadedFile("different.wav", audio_fixture()["raw"], content_type="audio/wav")
        self.assertEqual(self.upload(attachment=changed).status_code, 409)
        self.assertEqual(self.client.post("/casework/", self.fields).status_code, 409)
        self.assertEqual((Case.objects.count(), CaseAttachment.objects.count()), (1, 1))

    def test_disk_failure_rolls_back_case_source_evidence_and_retry_succeeds(self):
        with patch.object(self.storage, "put", side_effect=OSError("synthetic disk failure")):
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual((Case.objects.count(), CaseSource.objects.count(), CaseEvidence.objects.count()), (0, 0, 0))
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual((Case.objects.count(), CaseAttachment.objects.count()), (1, 1))

    def test_invalid_consent_proof_csrf_or_content_never_creates_case(self):
        self.assertEqual(self.upload(synthetic_only="no").status_code, 400)
        self.assertEqual(self.upload(confirmation="0" * 64).status_code, 403)
        self.assertEqual(self.upload(csrfmiddlewaretoken="").status_code, 403)
        self.assertEqual(self.upload(attachment=SimpleUploadedFile("bad.wav", b"bad", content_type="audio/wav")).status_code, 409)
        self.assertEqual(Case.objects.count(), 0)

    def test_feature_off_text_only_compatibility_and_freeze_blocks_new_intake(self):
        with override_settings(FATWA_BROWSER_AUDIO_ENABLED=False):
            page = self.client.get("/casework/")
            self.assertNotContains(page, "data-browser-audio")
            self.assertNotIn("script-src", page["Content-Security-Policy"])
            self.assertEqual(self.upload().status_code, 400)
            response = post(self.client, "/casework/", {
                "question": "نص اصطناعي دون ملف", "request_id": hidden(page, "request_id"),
                "confirmation": hidden(page, "confirmation"),
            }, page)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"], "FROZEN")
        self.assertEqual(self.upload().status_code, 503)
        with self.assertRaises(MaintenanceUnavailable):
            submit_intake(question="مرفوض", requester_id="synthetic", request_id="new", attachment=audio_fixture())
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(CaseAttachment.objects.count(), 0)


@override_settings(FATWA_BROWSER_AUDIO_ENABLED=True, FATWA_CASEWORK_WEB_ENABLED=True)
class RecorderPolicyTests(SimpleTestCase):
    def test_only_trusted_html_recorder_receives_permission_not_bytes_or_escaped_text(self):
        marker = b'<fieldset data-browser-audio data-input-name="attachment">'
        with patch.dict("os.environ", FATWA_PRODUCTION="0"):
            for response in (
                HttpResponse(marker, content_type="audio/wav"),
                HttpResponse("&lt;fieldset data-browser-audio data-input-name=&#x27;attachment&#x27;&gt;"),
                HttpResponse(marker, headers={"Content-Security-Policy": "sandbox; default-src 'none'"}),
            ):
                secured = private(response)
                self.assertNotIn("script-src", secured["Content-Security-Policy"])
                self.assertNotIn("Permissions-Policy", secured)
            permitted = private(private(HttpResponse(marker)))
            self.assertEqual(permitted["Content-Security-Policy"].count("script-src"), 1)
            self.assertIn("media-src 'self' blob:", permitted["Content-Security-Policy"])
