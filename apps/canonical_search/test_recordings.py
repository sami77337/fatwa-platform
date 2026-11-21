"""Real recording rows, immutable segment pins and cross-policy composition."""

import uuid
from dataclasses import replace
from hashlib import sha256
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.private_media.filesystem import FileSystemStorage
from apps.public_answer_media import services as recordings
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction
from apps.public_answer_media.test_support import FEATURES as MEDIA_FEATURES
from apps.public_answer_media.test_support import TEXT, MediaFixture, audio
from tests.casework.test_http import hidden, post

from . import services, views
from .models import SearchDocument, SearchGeneration
from .recordings import RecordingSources
from .test_support import FixtureAuthority, SearchFixture

FEATURES = {
    **MEDIA_FEATURES,
    "FATWA_CANONICAL_SEARCH_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}


class RecordingFixture(MediaFixture):
    build = SearchFixture.build
    search = SearchFixture.search

    def setUp(self):
        super().setUp()
        self.search_authority = FixtureAuthority(self.receipt["public_ref"])
        configured = override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=self.search_authority)
        configured.enable()
        self.addCleanup(configured.disable)

    def reviewed(self):
        return self.review(self.save())


@override_settings(**FEATURES)
class RecordingSearchTests(RecordingFixture, TransactionTestCase):
    def test_fts_result_opens_exact_reviewed_segment_of_actual_original(self):
        row = self.reviewed()
        self.build()
        hit = self.search("تفريغ", kind="RECORDING_TRANSCRIPT")["results"][0]
        source = RecordingTranscript.objects.get(pk=row["id"])
        self.assertEqual(hit["pin"]["version"], source.number)
        self.assertEqual(hit["pin"]["transcript_digest"], source.digest)
        self.assertEqual(hit["pin"]["part_id"], str(self.part.pk))
        self.assertEqual(hit["pin"]["part_sha256"], sha256(audio()).hexdigest())
        self.assertEqual(hit["pin"]["segment_sha256"], source.segments[0]["sha256"])
        self.assertEqual((hit["pin"]["start_ms"], hit["pin"]["end_ms"]), (1000, 2500))
        with recordings.segment_projection(
            **self.common, transcript_id=row["id"], index=0
        ) as opened:
            self.assertEqual(opened["text"], TEXT[:21])
            self.assertEqual(opened["pin"]["part_sha256"], hit["pin"]["part_sha256"])
            self.assertEqual(
                opened["audio_url"],
                f"/casework/staff/recording-transcripts/{row['id']}/audio/#t=1,2.5",
            )
        self.assertEqual(
            hit["segment_url"], f"/casework/staff/recording-transcripts/{row['id']}/segments/0/"
        )

    def test_static_recording_denial_preserves_independently_authorized_question(self):
        self.reviewed()
        self.build()
        self.authority.denied.add("READ_TRANSCRIPT")
        self.assertEqual(self.search("تفريغ")["total"], 0)
        ordinary = self.search("requester")
        self.assertEqual(ordinary["total"], 1)
        self.assertEqual(ordinary["indexes"][0]["state"], "CURRENT")

    def test_disabled_missing_or_unversioned_optional_policy_never_leaks_recording(self):
        self.reviewed()
        self.build()
        for changes in (
            {"FATWA_PUBLIC_ANSWER_MEDIA_ENABLED": False},
            {"FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY": None},
            {"FATWA_RESEARCH_WORKSPACE_RIGHTS": None},
        ):
            with self.subTest(changes=tuple(changes)), override_settings(**changes):
                self.assertEqual(self.search("تفريغ")["total"], 0)
                self.assertEqual(self.search("requester")["total"], 1)
        with patch.object(self.authority, "projection_epoch", return_value=None):
            self.assertEqual(self.search("تفريغ")["total"], 0)
            self.assertEqual(self.search("requester")["total"], 1)

    def test_static_withdrawal_removes_segment_without_invalidating_question_index(self):
        row = self.reviewed()
        self.build()
        self.review(row, action="WITHDRAW")
        self.assertEqual(self.search("تفريغ")["total"], 0)
        self.assertEqual(self.search("requester")["total"], 1)

    def test_new_text_revision_is_stale_and_has_no_inherited_review(self):
        self.reviewed()
        self.build()
        changed = self.save(
            text="نص ثان اصطناعي له صياغة جديدة لا يرث مراجعة سابقة.", expected_version=1
        )
        stale = self.search("تفريغ")
        self.assertEqual(stale["total"], 0)
        self.assertEqual(stale["indexes"][0]["state"], "STALE")
        self.build()
        self.assertEqual(self.search("صياغة")["total"], 0)
        self.review(changed)
        self.assertEqual(self.search("صياغة")["indexes"][0]["state"], "STALE")
        self.build()
        hits = self.search("نص", kind="RECORDING_TRANSCRIPT")["results"]
        self.assertEqual(hits[0]["pin"]["version"], 2)
        self.assertEqual(hits[0]["pin"]["transcript_id"], changed["id"])

    def test_final_search_callback_revoking_recording_read_rejects_entire_result(self):
        self.reviewed()
        self.build()
        count = 0

        def deny(values):
            nonlocal count
            if values["action"] == "SEARCH":
                count += 1
                if count == 2:
                    self.authority.denied.add("READ_TRANSCRIPT")

        self.search_authority.hook = deny
        with self.assertRaises(cases.CaseConflict):
            self.search("تفريغ")
        self.assertEqual(count, 2)

    def test_late_media_callback_revoking_search_permission_rolls_back_rebuild(self):
        self.reviewed()

        def revoke(values):
            if values["action"] == "READ_TRANSCRIPT":
                self.search_authority.denied.add("REBUILD")

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.build()
        self.assertFalse(SearchGeneration.objects.exists())
        self.assertFalse(SearchDocument.objects.exists())

    def test_reviewers_current_scope_and_late_identity_change_are_required(self):
        self.reviewed()
        self.build()
        reviewer = self.directory.identities["other"]
        self.directory.identities["other"] = replace(reviewer, case_keys=frozenset())
        self.assertEqual(self.search("تفريغ")["total"], 0)
        self.assertEqual(self.search("requester")["total"], 1)
        self.directory.identities["other"] = reviewer

        def revoke(values):
            if values["action"] == "READ_TRANSCRIPT":
                self.directory.identities["editor"] = replace(
                    self.directory.identities["editor"], active=False
                )

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.search("تفريغ")

    def test_sql_rejects_forged_audio_time_even_with_matching_generation_manifest(self):
        self.reviewed()
        original = services._seal

        def forged(row):
            if isinstance(row, SearchGeneration):
                for entry in row.manifest:
                    if entry["kind"] == "RECORDING_TRANSCRIPT":
                        entry["pin"]["start_ms"] = 2000
            if isinstance(row, SearchDocument) and row.kind == "RECORDING_TRANSCRIPT":
                row.pin["start_ms"] = 2000
            return original(row)

        with (
            self.assertRaisesRegex(DatabaseError, "recording coordinates differ from source"),
            patch.object(services, "_seal", side_effect=forged),
        ):
            self.build()
        self.assertFalse(SearchGeneration.objects.exists())


@override_settings(**FEATURES)
class RecordingSearchHTTPTests(RecordingFixture, TransactionTestCase):
    def login(self):
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        response = post(
            self.client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303, response.content)
        return self.client.get("/casework/staff/")

    def submit(self, action, response, **fields):
        return post(
            self.client,
            "/casework/staff/",
            {"action": action, "case_ref": self.receipt["public_ref"], **fields},
            response,
        )

    def query(self, page):
        return self.submit(
            "cs_search",
            page,
            query="تفريغ",
            mode="FTS",
            kind="RECORDING_TRANSCRIPT",
            page="1",
            scope="CASE",
        )

    def indexed(self):
        page = self.submit("cs_open", self.login())
        self.assertEqual(page.status_code, 200, page.content)
        page = self.submit("cs_rebuild", page, state=hidden(page, "state"))
        self.assertEqual(page.status_code, 200, page.content)
        return page

    def test_native_search_to_exact_segment_audio_and_current_revocation(self):
        row = self.reviewed()
        page = self.query(self.indexed())
        url = f"/casework/staff/recording-transcripts/{row['id']}/segments/0/"
        self.assertContains(page, url)
        opened = self.client.get(url)
        self.assertContains(
            opened, f"/casework/staff/recording-transcripts/{row['id']}/audio/#t=1,2.5"
        )
        original = self.client.get(f"/casework/staff/recording-transcripts/{row['id']}/audio/")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.content, audio())
        self.assertIn("no-store", original["Cache-Control"])
        anonymous = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(url)
        self.assertNotEqual(anonymous.status_code, 200)
        self.authority.denied.add("READ_TRANSCRIPT")
        self.assertNotEqual(self.client.get(url).status_code, 200)
        denied_audio = self.client.get(f"/casework/staff/recording-transcripts/{row['id']}/audio/")
        self.assertNotEqual(denied_audio.status_code, 200)
        self.assertNotEqual(denied_audio.content, audio())

    def test_late_render_real_withdrawal_rejects_html_and_rolls_back_withdrawal(self):
        row = self.reviewed()
        page = self.indexed()
        original = views.render
        before = TranscriptAction.objects.count()

        def withdraw(*args, **kwargs):
            rendered = original(*args, **kwargs)
            self.review(row, action="WITHDRAW", request_key=uuid.uuid4())
            return rendered

        with patch.object(views, "render", side_effect=withdraw):
            denied = self.query(page)
        self.assertEqual(denied.status_code, 409, denied.content)
        self.assertNotContains(denied, TEXT[:21], status_code=409)
        self.assertEqual(TranscriptAction.objects.count(), before)


class ReadHookStorage(FileSystemStorage):
    hook = None

    def get(self, original):
        raw = super().get(original)
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        return raw


@override_settings(**FEATURES)
class RecordingSearchStorageTests(RecordingFixture, TransactionTestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="fatwa-search-recording-")
        self.addCleanup(directory.cleanup)
        self.storage = ReadHookStorage(directory.name, synthetic_fixtures_only=True)
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)
        super().setUp()

    def test_missing_actual_original_excludes_only_recording_text(self):
        self.reviewed()
        self.build()
        (self.storage.root / "objects" / self.part.storage_key).unlink()
        self.assertEqual(self.search("تفريغ")["total"], 0)
        self.assertEqual(self.search("requester")["total"], 1)

    def test_final_original_read_cannot_revoke_search_after_its_last_permission_callback(self):
        self.reviewed()
        self.build()
        # The final physical reads now have their own phase, followed by pure
        # checks. Arm at that phase; patching the former combined wrapper would
        # no longer exercise an actual storage callback.
        original = RecordingSources.verify_bytes
        fired = []

        def arm_final_read(context):
            def revoke():
                fired.append(True)
                self.search_authority.denied.add("SEARCH")

            self.storage.hook = revoke
            return original(context)

        with patch.object(RecordingSources, "verify_bytes", arm_final_read):
            with self.assertRaises(cases.CaseConflict):
                self.search("تفريغ")
        self.assertEqual(fired, [True])
