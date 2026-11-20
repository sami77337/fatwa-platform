"""Native CSRF/authentication and whole-response source revocation; no browser bypass."""

import re
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationAction
from apps.private_media.filesystem import FileSystemStorage
from tests.casework.test_http import post

from . import services, views
from .boundaries import assert_projection_state, assert_snapshot
from .models import PublicMediaAction, RecordingTranscript, TranscriptAction
from .test_support import CREDENTIALS, FEATURES, TEXT, MediaFixture, audio


class CallbackFilesystem(FileSystemStorage):
    hook = None

    def get(self, original):
        raw = super().get(original)
        if self.hook:
            self.hook(original)
        return raw


@override_settings(**FEATURES)
class MediaHTTPTests(MediaFixture, TransactionTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="recording-originals-")
        self.addCleanup(folder.cleanup)
        self.storage = CallbackFilesystem(
            Path(folder.name) / "private", synthetic_fixtures_only=True
        )
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)
        super().setUp()
        self.client = self.client_for("editor")
        self.url = f"/library-preview/publications/{self.publication.pk}/recordings/"

    def client_for(self, subject=None):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        if subject:
            page = client.get("/casework/staff/login/")
            response = post(
                client, "/casework/staff/login/", {"credential": CREDENTIALS[subject]}, page
            )
            self.assertEqual(response.status_code, 303, response.content)
        return client

    def desk(self, client=None):
        client = client or self.client
        page = client.get("/casework/staff/")
        return post(
            client,
            "/casework/staff/",
            {"action": "pm_open", "case_ref": self.receipt["public_ref"]},
            page,
        )

    def save_form(self, **changes):
        fields = {
            "action": "pm_save_transcript",
            "case_ref": self.receipt["public_ref"],
            "revision": "3",
            "evidence_version": "1",
            "request_key": str(uuid.uuid4()),
            "note": "تصحيح بشري بعد الاستماع",
            "part_id": str(self.part.pk),
            "text": TEXT,
            "change_kind": "EDITORIAL",
            "expected_version": "0",
        }
        fields.update(
            {
                f"{name}_{index}": ""
                for index in range(services.MAX_SEGMENTS)
                for name in ("quote", "start_ms", "end_ms")
            }
        )
        fields.update(quote_0=TEXT[:21], start_ms_0="1000", end_ms_0="2500")
        return {**fields, **changes}

    def test_native_editor_exact_fields_and_authenticated_recording_player(self):
        page = self.desk()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "transcript-save")
        response = post(self.client, "/casework/staff/", self.save_form(), page)
        self.assertEqual(response.status_code, 200, response.content)
        row = RecordingTranscript.objects.get()
        self.assertEqual(row.subject_id, "editor")
        self.assertEqual(row.text, TEXT)
        response = self.client.get(f"/casework/staff/recording-transcripts/{row.pk}/audio/")
        self.assertEqual(response.status_code, 200, response.content[:100])
        self.assertEqual(response.content, audio())
        self.assertNotIn("private-original", response["Content-Disposition"])
        self.assertEqual(
            self.client_for()
            .get(f"/casework/staff/recording-transcripts/{row.pk}/audio/")
            .status_code,
            403,
        )
        response = post(self.client, "/casework/staff/", self.save_form(extra="forbidden"), page)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RecordingTranscript.objects.count(), 1)

    def test_actual_storage_reader_revocation_after_projection_closes_is_still_rejected(self):
        self.review(self.save())
        with services.search_projection(**self.common) as result:
            pin = result["snapshot"]
        reads = []
        self.storage.hook = lambda original: reads.append(original.sha256)
        assert_projection_state(pin)
        self.assertEqual(reads, [], "pure cross-case final check cannot call storage adapters")
        self.storage.hook = lambda original: self.authority.denied.add("READ_TRANSCRIPT")
        with self.assertRaisesMessage(services.cases.CaseConflict, "recording_projection_changed"):
            assert_snapshot(pin)

    def test_existing_publication_detail_has_a_real_guarded_recording_entry(self):
        self.release(self.review(self.save()))
        client = self.client_for()
        detail_url = f"/library-preview/editions/{self.publication.pk}/"
        response = client.get(detail_url)
        self.assertEqual(response.status_code, 200, response.content)
        link = re.search(
            r'<a href="([^"]+)">فتح التسجيل والتفريغ المراجع</a>', response.content.decode()
        )
        self.assertIsNotNone(link)
        recording = client.get(link.group(1))
        self.assertEqual(recording.status_code, 200, recording.content)
        self.assertContains(recording, TEXT)
        self.assertContains(recording, "<audio")
        with override_settings(FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED=False):
            self.assertNotContains(client.get(detail_url), "فتح التسجيل والتفريغ المراجع")

    def test_native_independent_review_release_and_anonymous_audio_segment(self):
        page = self.desk()
        response = post(self.client, "/casework/staff/", self.save_form(), page)
        self.assertEqual(response.status_code, 200, response.content)
        row = RecordingTranscript.objects.get()
        reviewer = self.client_for("other")
        page = self.desk(reviewer)
        fields = {
            "action": "pm_review_transcript",
            "case_ref": self.receipt["public_ref"],
            "revision": "3",
            "evidence_version": "1",
            "request_key": str(uuid.uuid4()),
            "note": "راجعت النص والتوقيت",
            "transcript_id": str(row.pk),
            "command": "REVIEW",
            "confirmed": "yes",
            "expected_actions": "0",
        }
        response = post(reviewer, "/casework/staff/", fields, page)
        self.assertEqual(response.status_code, 200, response.content)
        released = self.release({"id": str(row.pk)})
        public_client = self.client_for()
        response = public_client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, TEXT)
        self.assertNotContains(response, "PRIVATE")
        self.assertNotContains(response, self.receipt["public_ref"])
        self.assertNotContains(response, str(self.part.pk))
        self.assertNotContains(response, "autoplay")
        audio_response = public_client.get(f"/library-preview/recordings/{released['id']}/audio/")
        self.assertEqual(audio_response.status_code, 200)
        self.assertEqual(audio_response.content, audio())
        segment = public_client.get(f"/library-preview/recordings/{released['id']}/segments/0/")
        self.assertEqual(segment.status_code, 200, segment.content)
        self.assertContains(segment, "#t=1,2.5")

    def test_missing_file_or_media_policy_preserves_only_current_authorized_text(self):
        released = self.release(self.review(self.save()))
        object_path = self.storage.root / "objects" / self.part.storage_key
        object_path.unlink()
        response = self.client_for().get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, self.publication.body)
        self.assertNotContains(response, "<audio")
        self.assertNotContains(response, TEXT)
        self.assertEqual(
            self.client_for()
            .get(f"/library-preview/recordings/{released['id']}/audio/")
            .status_code,
            404,
        )
        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=None):
            self.assertEqual(self.client_for().get(self.url).status_code, 404)

    def test_missing_optional_authority_does_not_grant_or_remove_sound_text(self):
        self.release(self.review(self.save()))
        for setting in (
            "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY",
            "FATWA_CASEWORK_IDENTITY_PROVIDER",
            "FATWA_RESEARCH_WORKSPACE_RIGHTS",
        ):
            with override_settings(**{setting: None}):
                response = self.client_for().get(self.url)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertContains(response, self.publication.body)
                self.assertNotContains(response, TEXT)
                self.assertNotContains(response, "<audio")

    def test_late_public_media_withdrawal_removes_media_without_stale_text_reuse(self):
        released = self.release(self.review(self.save()))
        original = views.render

        def withdraw(request, template, context):
            if context.get("recordings"):
                self.decide(released, "WITHDRAW")
            return original(request, template, context)

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client_for().get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, self.publication.body)
        self.assertNotContains(response, "<audio")
        self.assertNotContains(response, TEXT)
        self.assertFalse(PublicMediaAction.objects.filter(action="WITHDRAW").exists())

    def test_late_canonical_withdrawal_denies_whole_page_not_optional_fallback(self):
        self.release(self.review(self.save()))
        original = views.render

        def withdraw(request, template, context):
            publication.act(
                **{**self.common, "subject_id": "publisher"},
                edition_id=str(self.publication.pk),
                action="WITHDRAW",
            )
            self.authority.denied.add("PUBLIC_AUDIO")
            return original(request, template, context)

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client_for().get(self.url)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotContains(response, self.publication.body, status_code=404)
        self.assertFalse(PublicationAction.objects.filter(action="WITHDRAW").exists())

    def test_late_native_render_revocation_rolls_back_new_transcript(self):
        page = self.desk()
        original = views.render

        def revoke(request, template, context):
            self.authority.denied.add("READ_TRANSCRIPT")
            return original(request, template, context)

        with patch.object(views, "render", side_effect=revoke):
            response = post(self.client, "/casework/staff/", self.save_form(), page)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(RecordingTranscript.objects.exists())

    def test_revoked_recorded_reviewer_and_current_source_rights_deny_public_file(self):
        released = self.release(self.review(self.save()))
        url = f"/library-preview/recordings/{released['id']}/audio/"
        self.directory.identities["other"] = replace(
            self.directory.identities["other"], active=False
        )
        self.assertEqual(self.client_for().get(url).status_code, 404)
        self.directory.identities["other"] = replace(
            self.directory.identities["other"], active=True
        )
        self.rights.denied.add("publisher")
        self.assertEqual(self.client_for().get(url).status_code, 404)

    def test_late_native_transcript_withdrawal_rejects_stale_history(self):
        row = self.review(self.save())
        original = views.render

        def withdraw(request, template, context):
            self.review(row, action="WITHDRAW", subject_id="publisher")
            return original(request, template, context)

        with patch.object(views, "render", side_effect=withdraw):
            response = self.desk()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(TranscriptAction.objects.filter(action="WITHDRAW").exists())
