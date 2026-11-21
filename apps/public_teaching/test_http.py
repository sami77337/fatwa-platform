"""Real native forms, anonymous navigation, bytes and whole-response revocation."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.public_answer_media.test_support import audio
from apps.public_knowledge.models import PublicRevision
from tests.casework.test_http import post

from . import services, views
from .models import TeachingVersion
from .test_support import FEATURES, MATERIAL, TeachingFixture


@override_settings(**FEATURES)
class TeachingHTTPTests(TeachingFixture, TransactionTestCase):
    def desk(self, subject="editor"):
        client, page = self.staff_client(subject)
        page = post(
            client,
            "/casework/staff/",
            {"action": "open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertContains(page, 'value="pt_open"')
        page = post(
            client,
            "/casework/staff/",
            {"action": "pt_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        return client, page

    def save_form(self, profile, material):
        return {
            "action": "pt_save",
            "case_ref": self.receipt["public_ref"],
            "revision": str(self.pins()["expected_revision"]),
            "evidence_version": str(self.pins()["expected_evidence_version"]),
            "request_key": str(uuid.uuid4()),
            "note": "نسبة بشرية للنسخ المحددة",
            "confirmed": "yes",
            "kind": "SCHOLAR_MATERIAL",
            "title": "مادة منسوبة من المكتب",
            "summary": "وصف عام",
            "item_id": "",
            "expected_version": "0",
            "profile": services.selection(profile),
            "material": services.selection(material),
            "attribution": "اختيار بشري صريح لا تطابق أسماء",
        }

    def test_native_csrf_save_independent_review_release_and_exact_material_link(self):
        profile = self.release_record(self.save_record("SCHOLAR"))
        profile = PublicRevision.objects.get(pk=profile["id"])
        material = self.material()
        client, page = self.desk()
        fields = self.save_form(profile, material)
        self.assertContains(page, services.selection(profile))
        self.assertContains(page, services.selection(material))
        self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
        response = post(client, "/casework/staff/", {**fields, "unexpected": "x"}, page)
        self.assertEqual(response.status_code, 400)
        response = post(client, "/casework/staff/", fields, page)
        self.assertEqual(response.status_code, 200, response.content)
        row = TeachingVersion.objects.get()
        for index, (command, subject) in enumerate(
            (("REVIEW", "other"), ("APPROVE", "publisher"), ("RELEASE", "publisher"))
        ):
            client, page = self.desk(subject)
            self.assertContains(page, f'data-command="{command}"')
            response = post(
                client,
                "/casework/staff/",
                {
                    "action": "pt_decide",
                    "case_ref": self.receipt["public_ref"],
                    "revision": str(self.pins()["expected_revision"]),
                    "evidence_version": str(self.pins()["expected_evidence_version"]),
                    "version_id": str(row.pk),
                    "command": command,
                    "expected_actions": str(index),
                    "minutes": "15" if command == "RELEASE" else "0",
                    "request_key": str(uuid.uuid4()),
                    "note": "راجعت الأصل والنسبة والإتاحة المحددة",
                    "confirmed": "yes",
                },
                page,
            )
            self.assertEqual(response.status_code, 200, response.content)
        public = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = public.get(f"/library-preview/teaching/scholars/{profile.series_id}/")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "الفتاوى المنسوبة")
        self.assertContains(page, "الدروس المنسوبة")
        self.assertContains(page, "اختيار بشري صريح لا تطابق أسماء")
        with services.public_projection() as current:
            descriptor = current.scholar(profile.series_id)["materials"][0]["material"]
        linked = public.get(descriptor["url"])
        self.assertEqual(linked.status_code, 200, linked.content)
        self.assertContains(linked, f'href="{descriptor["url"]}file/"')
        content = public.get(descriptor["url"] + "file/")
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content.content, MATERIAL)

    def test_anonymous_series_lesson_range_and_revocation_hide_original_and_private_fields(self):
        rows = self.complete()
        first = rows["lessons"][0]
        catalog = self.client.get("/library-preview/teaching/")
        self.assertEqual(catalog.status_code, 200, catalog.content)
        path = f"/library-preview/teaching/series/{rows['series']['public_id']}/"
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "سلسلة عامة ذات ترتيب موثق")
        lesson = self.client.get(path + f"lessons/{first['public_id']}/")
        self.assertEqual(lesson.status_code, 200, lesson.content)
        self.assertContains(lesson, 'rel="next"')
        self.assertContains(lesson, '<audio class="library-player" controls')
        self.assertNotContains(lesson, "autoplay")
        for forbidden in (
            "PRIVATE",
            self.receipt["public_ref"],
            self.second["public_ref"],
            "auth_epoch",
            "provider_id",
        ):
            self.assertNotContains(lesson, forbidden)
        audio_url = f"/library-preview/teaching/lessons/{first['public_id']}/1/media/"
        content = self.client.get(audio_url, HTTP_RANGE="bytes=0-43")
        self.assertEqual(content.status_code, 206, content.content)
        self.assertEqual(content.content, audio()[:44])
        self.assertEqual(self.client.get(audio_url).content, audio())
        self.teaching_authority.denied.add("PUBLIC_LESSON_CONTENT")
        for path in (path, audio_url):
            response = self.client.get(path, HTTP_RANGE="bytes=0-43")
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("Content-Range", response)

    def test_late_render_revocation_rolls_back_native_write_and_discards_public_content(self):
        profile = self.release_record(self.save_record("SCHOLAR"))
        profile = PublicRevision.objects.get(pk=profile["id"])
        material = self.material()
        client, page = self.desk()
        original = views.render

        def revoke(request, template, context):
            result = original(request, template, context)
            self.teaching_authority.denied.add("READ_SOURCE")
            return result

        with patch.object(views, "render", side_effect=revoke):
            denied = post(client, "/casework/staff/", self.save_form(profile, material), page)
        self.assertEqual(denied.status_code, 409, denied.content)
        self.assertFalse(TeachingVersion.objects.exists())
        self.teaching_authority.denied.clear()
        row = self.release_teaching(
            self.save_teaching(
                "SCHOLAR_MATERIAL",
                profile=services.selection(profile),
                material=services.selection(material),
                attribution="نسبة بشرية موثقة",
            )
        )
        with patch.object(views, "render", side_effect=revoke):
            refused = self.client.get(f"/library-preview/teaching/scholars/{profile.series_id}/")
        self.assertEqual(refused.status_code, 404, refused.content)
        self.assertNotContains(refused, row["title"], status_code=404)

    def test_source_choice_requires_exact_metadata_permission_and_current_case_scope(self):
        _, first, _ = self.metadata()
        self.teaching_authority.denied.add(("READ_SOURCE", "LESSON_METADATA"))
        client, page = self.desk()
        self.assertNotContains(page, services.selection(first))
        self.teaching_authority.denied.clear()
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        page = post(
            client,
            "/casework/staff/",
            {"action": "pt_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertNotContains(page, services.selection(first))
        self.assertNotContains(page, "PRIVATE series title")
