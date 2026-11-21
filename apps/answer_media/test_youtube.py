"""Typed link originals, native authoring and current private-access boundaries."""

import uuid
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.db import IntegrityError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services, views
from . import tests as old_tests
from .models import AnswerManifest, AnswerPart

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    "FATWA_ANSWER_LINKS_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}
LINK = {"url": "https://youtu.be/aB3dE6gH9_k", "label": "مرجع فيديو اصطناعي اختاره المفتي"}


class LinkFixture:
    approve = old_tests.AnswerMediaTests.approve
    release = old_tests.AnswerMediaTests.release
    private = old_tests.AnswerMediaTests.private

    def setUp(self):
        super().setUp()
        old_tests.AnswerMediaTests.setUp(self)
        self.directory.projection_epoch = lambda: repr(
            (
                self.directory.provider_id,
                self.directory.current,
                self.directory.current.valid_until > timezone.now(),
            )
        )

    def save_link(self, **changes):
        case = Case.objects.get(pk=self.common["case_id"])
        return services.save_multipart_answer(
            **{
                **self.common,
                "expected_revision": case.revision,
                "expected_evidence_version": case.evidence_version,
                "text": "جواب بشري يحيل إلى رابط خارجي دون جلب محتواه",
                "files": [],
                "links": [dict(LINK)],
                **changes,
            }
        )


@override_settings(**FEATURES)
class YouTubeLinkTests(LinkFixture, TransactionTestCase):
    def test_exact_original_and_derived_url_are_distinct_immutable_manifest_pins(self):
        self.save_link()
        row = AnswerPart.objects.get(kind="YOUTUBE_LINK")
        self.assertEqual(bytes(row.original), LINK["url"].encode())
        self.assertEqual(row.sha256, sha256(LINK["url"].encode()).hexdigest())
        self.assertEqual(row.metadata["url"], "https://www.youtube.com/watch?v=aB3dE6gH9_k")
        self.assertEqual(row.metadata["availability"], "UNVERIFIED")
        self.assertEqual(row.media_type, "text/uri-list")
        self.assertEqual(row.storage_backend, "inline-database-v1")
        self.assertEqual(
            services.validate_for_approval(row.manifest.answer)["parts"][1]["metadata"],
            row.metadata,
        )
        self.assertEqual(Case.objects.get().evidence_version, 1)

    def test_separate_approval_release_reorder_and_revision_do_not_inherit_availability(self):
        self.save_link(
            links=[
                LINK,
                {"url": "https://www.youtube.com/watch?v=ZyXwVuTsR_q", "label": "مرجع ثان"},
            ]
        )
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.approve()
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.release()
        before = self.private()["package"]["parts"][1:]
        self.save_link(links=[], retained_part_ids=[row["id"] for row in reversed(before)])
        current = services.staff_snapshot(**self.common)["latest_package"]["parts"][1:]
        self.assertEqual(
            [row["sha256"] for row in current], [row["sha256"] for row in reversed(before)]
        )
        self.assertNotEqual(current[0]["id"], before[1]["id"])
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.approve()
        self.release()
        read = services.requester_read(
            token=self.receipt["token"], part_id=current[0]["id"], synthetic_fixtures_only=True
        )
        self.assertEqual(read["raw"], b"https://www.youtube.com/watch?v=ZyXwVuTsR_q")
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=self.receipt["token"], part_id=before[0]["id"], synthetic_fixtures_only=True
            )

    def test_default_off_invalid_urls_and_stale_commands_never_add_parts(self):
        with override_settings(FATWA_ANSWER_LINKS_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.save_link()
        for url in (
            "javascript:alert(1)",
            "http://youtu.be/aB3dE6gH9_k",
            "https://youtube.com.evil/watch?v=aB3dE6gH9_k",
            "https://youtube.com@evil.test/watch?v=aB3dE6gH9_k",
            "https://youtu.be/aB3dE6gH9_k\n",
            "https://www.youtube.com/watch?v=aB3dE6gH9_k&redirect=https://evil.test",
            "https://127.0.0.1/watch?v=aB3dE6gH9_k",
            "https://youtu.be/%61B3dE6gH9_k",
        ):
            with self.subTest(url=url), self.assertRaises(cases.CaseConflict):
                self.save_link(links=[{"url": url, "label": "مثال"}])
        self.assertFalse(AnswerPart.objects.exists())
        self.save_link()
        with self.assertRaises(cases.CaseConflict):
            self.save_link(expected_revision=1)
        self.assertEqual(AnswerManifest.objects.count(), 1)

    def test_sql_rejects_metadata_forgery_and_missing_required_keys(self):
        original = AnswerPart.objects.create
        for change in (
            {"external": False},
            {"availability": "AVAILABLE"},
            {"url": "https://evil.test/"},
            {"video_id": None},
            {"label": None},
        ):

            def forged(**values):
                if values["kind"] == "YOUTUBE_LINK":
                    values["metadata"] = {**values["metadata"], **change}
                return original(**values)

            with (
                self.subTest(change=change),
                patch.object(AnswerPart.objects, "create", side_effect=forged),
            ):
                with self.assertRaises(IntegrityError):
                    self.save_link()
        self.assertFalse(AnswerManifest.objects.exists())

    def test_current_scope_foreign_tokens_and_late_identity_changes_are_denied(self):
        self.save_link()
        self.approve()
        self.release()
        part = self.private()["package"]["parts"][1]
        key = uuid.uuid4().hex
        other = cases.intake_case(
            original_question="قضية أخرى",
            requester_id=key,
            source_event_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=other["token"], part_id=part["id"], synthetic_fixtures_only=True
            )
        before = AnswerManifest.objects.count()
        original = cases._staff

        def revoke(case):
            result = original(case)
            self.directory.current = replace(self.directory.current, active=False)
            return result

        with (
            patch.object(cases, "_staff", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_link()
        self.assertEqual(AnswerManifest.objects.count(), before)

    def test_late_private_capability_withdrawal_rejects_whole_link_projection(self):
        self.save_link()
        self.approve()
        self.release()
        original = services._projection

        def withdraw(case, manifest):
            result = original(case, manifest)
            cases.revoke_access(**self.common, requester_id="requester-one")
            return result

        with patch.object(services, "_projection", side_effect=withdraw):
            with self.assertRaises(cases.CaseConflict):
                self.private()
        self.assertEqual(self.private()["package"]["parts"][1]["metadata"]["label"], LINK["label"])


@override_settings(**FEATURES)
class YouTubeLinkHTTPTests(LinkFixture, TransactionTestCase):
    def page(self):
        self.client = Client(
            enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        login = post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(login.status_code, 303)
        page = self.client.get("/casework/staff/")
        return post(
            self.client,
            "/casework/staff/",
            {"action": "answer_media", "case_ref": self.receipt["public_ref"]},
            page,
        )

    def native_save(self, page):
        return self.client.post(
            "/casework/staff/",
            {
                "action": "answer_media_save",
                "case_ref": self.receipt["public_ref"],
                "revision": "1",
                "evidence_version": "1",
                "text": "جواب لم ينسخه البحث",
                "retain": "no",
                "synthetic_only": "yes",
                "answer_file": "",
                "youtube_url": LINK["url"],
                "youtube_label": LINK["label"],
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            },
        )

    def test_actual_campaign_form_saves_external_link_without_embed_or_false_download(self):
        page = self.page()
        self.assertContains(page, 'id="youtube-url"')
        saved = self.native_save(page)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertContains(saved, 'class="external-youtube"')
        self.assertContains(saved, 'rel="noopener noreferrer external"')
        self.assertNotContains(saved, "youtube.com/embed")
        self.assertNotContains(saved, "<iframe")
        self.assertEqual(AnswerPart.objects.filter(kind="YOUTUBE_LINK").count(), 1)
        denied = self.client.post(
            "/casework/staff/",
            {"action": "answer_media_save", "case_ref": self.receipt["public_ref"]},
        )
        self.assertEqual(denied.status_code, 403)

    def test_native_command_and_render_roll_back_on_late_revocation(self):
        page = self.page()
        before = CaseEvent.objects.count()
        original = views.render

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.directory.current = replace(self.directory.current, active=False)
            return result

        with patch.object(views, "render", side_effect=revoke):
            denied = self.native_save(page)
        self.assertNotEqual(denied.status_code, 200)
        self.assertNotIn(LINK["label"].encode(), denied.content)
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertFalse(AnswerPart.objects.exists())
