"""Native CSRF/authentication and whole-response source revocation; no browser bypass."""

import re
import tempfile
import uuid
from dataclasses import replace
from hashlib import sha256
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

    def test_exact_original_ranges_support_native_seek_without_source_transformation(self):
        transcript = self.review(self.save())
        released = self.release(transcript)
        raw = audio()
        routes = (
            (self.client, f"/casework/staff/recording-parts/{self.part.pk}/audio/"),
            (self.client, f"/casework/staff/recording-transcripts/{transcript['id']}/audio/"),
            (self.client_for(), f"/library-preview/recordings/{released['id']}/audio/"),
        )
        for client, path in routes:
            for requested, start, end in (
                ("bytes=0-", 0, len(raw) - 1),
                ("bytes=16044-32043", 16044, 32043),
                ("bytes=-44", len(raw) - 44, len(raw) - 1),
                ("bytes=96000-999999999", 96000, len(raw) - 1),
            ):
                with self.subTest(path=path, requested=requested):
                    response = client.get(path, HTTP_RANGE=requested)
                    self.assertEqual(response.status_code, 206, response.content[:100])
                    self.assertEqual(response.content, raw[start : end + 1])
                    self.assertEqual(response["Content-Range"], f"bytes {start}-{end}/{len(raw)}")
                    self.assertEqual(response["Content-Length"], str(end - start + 1))
                    self.assertEqual(response["Accept-Ranges"], "bytes")
                    self.assertEqual(response["ETag"], '"' + sha256(raw).hexdigest() + '"')
                    self.assertEqual(response["Content-Type"], "audio/wav")
                    self.assertIn("no-store", response["Cache-Control"])
                    self.assertIn("default-src 'none'", response["Content-Security-Policy"])
                    if path.startswith("/casework/"):
                        self.assertIn("sandbox", response["Content-Security-Policy"])
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, raw)
            self.assertNotIn("Content-Range", response)
            head = client.head(path, HTTP_RANGE="bytes=16044-32043")
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            self.assertEqual(head["Content-Length"], str(len(raw)))
            self.assertNotIn("Content-Range", head)

    def test_range_bounds_and_validator_never_select_an_alternative_original(self):
        transcript = self.review(self.save())
        path = f"/casework/staff/recording-transcripts/{transcript['id']}/audio/"
        for requested in (
            "bytes=96044-",
            "bytes=10-2",
            "bytes=-0",
            "bytes=-",
            "bytes=0-1,4-5",
            "items=0-10",
            "bytes=" + "9" * 30 + "-",
        ):
            with self.subTest(requested=requested):
                response = self.client.get(path, HTTP_RANGE=requested)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response.content, b"")
                self.assertEqual(response["Content-Range"], f"bytes */{len(audio())}")
                self.assertEqual(response["Content-Length"], "0")
        etag = '"' + sha256(audio()).hexdigest() + '"'
        accepted = self.client.get(path, HTTP_RANGE="bytes=44-45", HTTP_IF_RANGE=etag)
        self.assertEqual(accepted.status_code, 206)
        self.assertEqual(accepted.content, audio()[44:46])
        changed = self.client.get(path, HTTP_RANGE="bytes=44-45", HTTP_IF_RANGE='"old-source"')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.content, audio())
        self.assertNotIn("Content-Range", changed)

    def test_each_range_rechecks_reader_and_current_public_release(self):
        transcript = self.review(self.save())
        released = self.release(transcript)
        private_path = f"/casework/staff/recording-transcripts/{transcript['id']}/audio/"
        public_path = f"/library-preview/recordings/{released['id']}/audio/"
        public_client = self.client_for()
        self.assertEqual(self.client.get(private_path, HTTP_RANGE="bytes=0-43").status_code, 206)
        self.assertEqual(public_client.get(public_path, HTTP_RANGE="bytes=0-43").status_code, 206)
        self.authority.denied.add("READ_TRANSCRIPT")
        refused = self.client.get(private_path, HTTP_RANGE="bytes=44-100")
        self.assertEqual(refused.status_code, 404)
        self.assertNotIn("Content-Range", refused)
        self.assertNotIn("ETag", refused)
        self.authority.denied.clear()
        self.decide(released, "WITHDRAW")
        for requested in ("bytes=44-100", "bytes=999999999-"):
            refused = public_client.get(public_path, HTTP_RANGE=requested)
            self.assertEqual(refused.status_code, 404)
            self.assertNotIn("Content-Range", refused, "withdrawn source length must not leak")
            self.assertNotIn("ETag", refused)

    def test_late_current_rights_revocation_discards_already_built_range(self):
        transcript = self.review(self.save())
        released = self.release(transcript)
        path = f"/library-preview/recordings/{released['id']}/audio/"
        original = views._file_response

        def revoke(request, data):
            response = original(request, data)
            self.assertEqual(response.status_code, 206)
            self.rights.denied.add("publisher")
            return response

        with patch.object(views, "_file_response", side_effect=revoke):
            refused = self.client_for().get(path, HTTP_RANGE="bytes=0-43")
        self.assertEqual(refused.status_code, 404)
        self.assertNotIn("Content-Range", refused)
        self.assertNotIn("ETag", refused)
        self.assertNotEqual(refused.content, audio()[:44])

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

    def test_actual_segment_initializer_is_current_authorized_external_and_narrowly_scoped(self):
        transcript = self.review(self.save())
        released = self.release(transcript)
        private_path = f"/casework/staff/recording-transcripts/{transcript['id']}/segments/0/"
        public_path = f"/library-preview/recordings/{released['id']}/segments/0/"
        for client, path, asset in (
            (self.client, private_path, "/casework/staff/recording-player.js"),
            (self.client_for(), public_path, "/library-preview/recordings/player.js"),
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertContains(response, f'type="module" src="{asset}"')
                self.assertContains(response, 'data-start-ms="1000" data-end-ms="2500"')
                self.assertNotContains(response, "autoplay")
                policy = response["Content-Security-Policy"]
                self.assertIn("script-src 'self'", policy)
                self.assertNotIn("unsafe-inline", policy)
                self.assertNotIn("unsafe-eval", policy)
                self.assertNotIn("connect-src", policy)
                response = client.get(asset)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(response["Content-Type"].startswith("text/javascript"))
                self.assertIn(b"loadedmetadata", response.content)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertEqual(client.head(asset).content, b"")
        self.assertEqual(
            self.client_for().get("/casework/staff/recording-player.js").status_code, 403
        )
        self.assertEqual(
            self.client.get("/casework/staff/recording-player.js?start=1").status_code, 400
        )
        self.assertEqual(
            self.client_for().post("/library-preview/recordings/player.js").status_code, 405
        )
        with override_settings(FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED=False):
            self.assertEqual(
                self.client_for().get("/library-preview/recordings/player.js").status_code, 404
            )
        normal = self.client_for().get(self.url)
        self.assertNotIn("script-src", normal["Content-Security-Policy"])
        original = self.client.get(
            f"/casework/staff/recording-transcripts/{transcript['id']}/audio/"
        )
        self.assertIn("sandbox", original["Content-Security-Policy"])
        self.assertNotIn("script-src", original["Content-Security-Policy"])

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
