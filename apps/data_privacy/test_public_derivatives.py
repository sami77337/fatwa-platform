"""Real released copies, private originals and late public projection denials."""

from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.library_preview import services as preview
from apps.public_answer_media import public as recordings
from apps.public_answer_media import test_support as media_fixture
from apps.public_answer_media import views as media_views
from apps.public_collections import services as collections
from apps.public_collections import test_support as collection_fixture
from apps.public_knowledge import public as knowledge
from apps.public_knowledge import test_scholarly as scholarly_fixture
from apps.public_knowledge import tests as knowledge_fixture
from apps.public_knowledge import views as knowledge_views
from apps.public_teaching import services as teaching
from apps.public_teaching import test_support as teaching_fixture

from . import integration, services
from .catalog import locate
from .public_derivative_test_support import PrivacyAssertions


@override_settings(**knowledge_fixture.FEATURES)
class PublicKnowledgePrivacyTests(
    PrivacyAssertions, knowledge_fixture.CurationFixture, TransactionTestCase
):
    def setUp(self):
        super().setUp()
        self.scholar, self.parent, self.child, self.presentation, self.translation = (
            self.published()
        )
        self.enable_privacy()

    def test_unknown_and_denied_exact_child_remove_derived_graph_before_counts(self):
        self.admit_known(exclude=[("PUBLIC_KNOWLEDGE", self.child["id"])])
        with knowledge.projection() as result:
            self.assertNotIn(self.child["id"], result.records)
            self.assertEqual(result.presentations, {})
            self.assertEqual(len(result.topics), 1)
        self.label("PUBLIC_KNOWLEDGE", self.child["id"], "PUBLIC")
        self.privacy_grant("PUBLIC_KNOWLEDGE", self.child["id"], "PUBLISH")
        with knowledge.projection() as result:
            self.assertEqual(result.presentations, {})  # PUBLIC alone is not READ.
        self.privacy_grant("PUBLIC_KNOWLEDGE", self.child["id"], "READ", public=True)
        with knowledge.projection() as result:
            self.assertEqual(len(result.presentations), 2)
            self.assertEqual(len(result.topics), 2)
        self.assert_private_case(self.receipt["case_id"])
        self.assert_originals()

    def test_source_read_does_not_grant_republication_and_source_case_stays_private(self):
        self.admit_known()
        self.revoke("PUBLICATION", self.edition["id"], "PUBLISH")
        with knowledge.projection() as result:
            self.assertEqual(result.records, {})
        self.privacy_grant("PUBLICATION", self.edition["id"], "READ", subject="publisher")
        with knowledge.projection() as result:
            self.assertEqual(result.records, {})
        self.privacy_grant("PUBLICATION", self.edition["id"], "PUBLISH")
        with knowledge.projection() as result:
            self.assertEqual(len(result.records), 5)
        self.assert_private_case(self.receipt["case_id"])
        self.assert_originals()

    def test_last_domain_callback_rejects_already_rendered_native_page(self):
        self.admit_known()
        armed = False
        original_render, original_permit = knowledge_views.render, self.curation_authority.permits
        key = self.exact_grants[("PUBLIC_KNOWLEDGE", self.scholar["id"], "READ")]

        def render_then_arm(*args, **kwargs):
            nonlocal armed
            result = original_render(*args, **kwargs)
            armed = True
            return result

        def late_callback(**values):
            result = original_permit(**values)
            if armed:
                self.privacy_authority.grants.pop(key, None)
            return result

        with (
            patch.object(knowledge_views, "render", side_effect=render_then_arm),
            patch.object(self.curation_authority, "permits", side_effect=late_callback),
        ):
            response = self.page(self.scholar)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.scholar["payload"]["name"].encode(), response.content)
        self.privacy_grant("PUBLIC_KNOWLEDGE", self.scholar["id"], "READ", public=True)
        self.assertEqual(self.page(self.scholar).status_code, 200)
        self.assert_originals()


@override_settings(**scholarly_fixture.INTEGRATED)
class PublicRelationPrivacyTests(
    PrivacyAssertions, scholarly_fixture.IntegratedFixture, TransactionTestCase
):
    def test_related_publication_needs_the_current_derivative_publish_grant(self):
        self.presentation(self.relation())
        self.enable_privacy()
        self.admit_known()
        with knowledge.projection() as result:
            self.assertEqual(len(result.presentation(self.edition["id"])["related"]), 1)
        self.revoke("PUBLICATION", self.second_publication["id"], "PUBLISH")
        with knowledge.projection() as result:
            self.assertIn(self.second_publication["id"], result.sources)
            self.assertEqual(result.presentation(self.edition["id"])["related"], [])
        self.assertNotContains(self.client.get(self.public_url), "فتوى ثانية مصرح بها")
        self.privacy_grant("PUBLICATION", self.second_publication["id"], "PUBLISH")
        self.assertContains(self.client.get(self.public_url), "فتوى ثانية مصرح بها")
        self.assert_originals()


@override_settings(**collection_fixture.FEATURES)
class PublicCollectionPrivacyTests(
    PrivacyAssertions, collection_fixture.CollectionFixture, TransactionTestCase
):
    def setUp(self):
        super().setUp()
        self.parent = self.release_collection(self.create_collection(kind="TOPIC"))
        self.child = self.release_collection(
            self.create_collection(kind="TOPIC", parent_id=self.parent["id"])
        )
        self.enable_privacy()

    def test_parent_and_exact_member_publish_denials_remove_complete_collections(self):
        self.admit_known()
        with collections.public_projection() as rows:
            self.assertEqual(len(rows), 2)
        self.revoke("PUBLIC_COLLECTION", self.parent["id"], "READ")
        with collections.public_projection() as rows:
            self.assertEqual(rows, [])
        self.privacy_grant("PUBLIC_COLLECTION", self.parent["id"], "READ", public=True)
        self.revoke("PUBLICATION", self.edition["id"], "PUBLISH")
        with collections.public_projection() as rows:
            self.assertEqual(rows, [])
        self.privacy_grant("PUBLICATION", self.edition["id"], "PUBLISH")
        with collections.public_projection() as rows:
            self.assertEqual(len(rows), 2)
        self.assert_originals()

    def test_nonpublic_label_cannot_be_overridden_by_anonymous_grant(self):
        self.admit_known()
        self.label("PUBLIC_COLLECTION", self.parent["id"], "RESTRICTED")
        self.privacy_grant("PUBLIC_COLLECTION", self.parent["id"], "READ", public=True)
        with collections.public_projection() as rows:
            self.assertEqual(rows, [])
        page = self.client.get(self.collection_url(self.child))
        self.assertEqual(page.status_code, 404)
        self.assertNotIn(self.child["title"].encode(), page.content)
        self.assert_originals()

    def test_late_reclassification_closes_outer_projection_without_changing_sources(self):
        self.admit_known()
        with self.assertRaises(preview.PreviewUnavailable):
            with collections.public_projection() as rows:
                self.assertEqual(len(rows), 2)
                self.label("PUBLIC_COLLECTION", self.child["id"], "CONFIDENTIAL")
        # Failed read rolls back the attempted in-transaction label, not history.
        self.assertEqual(
            services.current(locate("PUBLIC_COLLECTION", self.child["id"])).level, "PUBLIC"
        )
        with collections.public_projection() as rows:
            self.assertEqual(len(rows), 2)
        self.assert_originals()


@override_settings(**teaching_fixture.FEATURES)
class PublicTeachingPrivacyTests(
    PrivacyAssertions, teaching_fixture.TeachingFixture, TransactionTestCase
):
    def setUp(self):
        super().setUp()
        self.released = self.complete()
        self.enable_privacy()

    def test_native_metadata_navigation_omits_private_recording_and_rejects_late_changes(self):
        self.admit_known()
        lesson = teaching.TeachingVersion.objects.get(pk=self.released["lessons"][0]["id"])
        url = f"/library-preview/knowledge/lessons/{lesson.lesson_metadata.series_id}/"
        recording_url = f"/library-preview/teaching/lessons/{lesson.item.public_id}/"
        page = self.client.get(url)
        self.assertContains(page, recording_url)
        self.assertEqual(len(page.context["recordings"]), 1)
        self.revoke("PUBLIC_TEACHING", lesson.pk, "READ")
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["recordings"], [])
        self.assertNotContains(page, recording_url)
        self.assertNotContains(page, lesson.title)
        self.privacy_grant("PUBLIC_TEACHING", lesson.pk, "READ", public=True)
        key = self.exact_grants[("PUBLIC_TEACHING", str(lesson.pk), "READ")]
        original = knowledge_views.render

        def render_then_revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.privacy_authority.grants.pop(key, None)
            return response

        with patch.object(knowledge_views, "render", side_effect=render_then_revoke):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.privacy_grant("PUBLIC_TEACHING", lesson.pk, "READ", public=True)
        self.assertContains(self.client.get(url), recording_url)
        self.assert_originals()

    def test_lesson_source_publish_and_child_read_are_independent_of_public_series(self):
        self.admit_known()
        lesson = teaching.TeachingVersion.objects.get(pk=self.released["lessons"][0]["id"])
        with teaching.public_projection() as current:
            self.assertEqual(len(current.catalog()["lessons"]), 2)
            self.assertEqual(len(current.catalog()["series"]), 1)
            self.assertEqual(len(list(current.catalog()["scholars"])), 1)
        self.revoke("SERIES_VERSION", lesson.series_version_id, "PUBLISH")
        with teaching.public_projection() as current:
            self.assertEqual(len(current.catalog()["lessons"]), 1)
            self.assertEqual(current.catalog()["series"], [])
        self.privacy_grant("SERIES_VERSION", lesson.series_version_id, "PUBLISH")
        self.revoke("ANSWER_PART", lesson.lesson_version.source_part_id, "PUBLISH")
        with teaching.public_projection() as current:
            self.assertEqual(current.catalog()["lessons"], [])
            self.assertEqual(current.catalog()["series"], [])
        self.privacy_grant("ANSWER_PART", lesson.lesson_version.source_part_id, "PUBLISH")
        self.revoke("PUBLIC_TEACHING", lesson.pk, "READ")
        with teaching.public_projection() as current:
            self.assertEqual(len(current.catalog()["lessons"]), 1)
            self.assertEqual(current.catalog()["series"], [])
        self.privacy_grant("PUBLIC_TEACHING", lesson.pk, "READ", public=True)
        with teaching.public_projection() as current:
            result = current.audio(lesson.item.public_id, lesson.number)
            self.assertEqual(result["raw"], media_fixture.audio())
        self.assert_private_case(self.second["case_id"])
        self.assert_originals()

    def test_public_material_read_does_not_publish_an_attribution(self):
        self.admit_known()
        material = self.released["material"]
        self.revoke("LIBRARY_VERSION", material.pk, "PUBLISH")
        with teaching.public_projection() as current:
            self.assertEqual(list(current.catalog()["scholars"]), [])
            self.assertEqual(len(current.catalog()["lessons"]), 2)
        self.privacy_grant("LIBRARY_VERSION", material.pk, "PUBLISH")
        with teaching.public_projection() as current:
            self.assertEqual(len(list(current.catalog()["scholars"])), 1)
        self.assert_originals()

    def test_last_source_callback_revokes_already_read_lesson_bytes(self):
        self.admit_known()
        lesson = teaching.TeachingVersion.objects.get(pk=self.released["lessons"][0]["id"])
        armed = False
        key = self.exact_grants[
            ("ANSWER_PART", str(lesson.lesson_version.source_part_id), "PUBLISH")
        ]

        def revoke_after_audio(values):
            if armed:
                self.privacy_authority.grants.pop(key, None)

        self.teaching_authority.hook = revoke_after_audio
        with self.assertRaises(preview.PreviewUnavailable):
            with teaching.public_projection() as current:
                self.assertEqual(
                    current.audio(lesson.item.public_id, lesson.number)["raw"],
                    media_fixture.audio(),
                )
                armed = True
        self.teaching_authority.hook = None
        self.privacy_grant("ANSWER_PART", lesson.lesson_version.source_part_id, "PUBLISH")
        with teaching.public_projection() as current:
            self.assertEqual(len(current.catalog()["lessons"]), 2)
        self.assert_originals()


@override_settings(**media_fixture.FEATURES)
class PublicMediaPrivacyTests(PrivacyAssertions, media_fixture.MediaFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.transcript = self.review(self.save())
        self.recording = self.release(self.transcript)
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.audio_url = f"/library-preview/recordings/{self.recording['id']}/audio/"
        self.enable_privacy()

    def test_explicit_public_copy_uses_private_transcript_without_publicizing_original(self):
        self.admit_known()
        with recordings.recording_projection(self.recording["id"]) as result:
            self.assertEqual(result["recording"]["text"], media_fixture.TEXT)
            self.assertEqual(result["file"]["raw"], media_fixture.audio())
        response = self.client.get(self.audio_url, HTTP_RANGE="bytes=0-15")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, media_fixture.audio()[:16])
        transcript = locate("RECORDING_TRANSCRIPT", self.transcript["id"])
        self.assertEqual(services.current(transcript).level, "CONFIDENTIAL")
        with self.assertRaises(services.PrivacyDenied):
            integration.public("RECORDING_TRANSCRIPT", self.transcript["id"])
        self.assert_private_case(self.receipt["case_id"])
        self.assert_originals()

    def test_read_or_public_label_alone_never_publishes_exact_transcript(self):
        self.admit_known()
        self.revoke("RECORDING_TRANSCRIPT", self.transcript["id"], "PUBLISH")
        self.privacy_grant("RECORDING_TRANSCRIPT", self.transcript["id"], "READ")
        self.assertEqual(self.client.get(self.audio_url).status_code, 404)
        self.privacy_grant("RECORDING_TRANSCRIPT", self.transcript["id"], "PUBLISH")
        self.revoke("PUBLIC_MEDIA", self.recording["id"], "READ")
        self.assertEqual(self.client.head(self.audio_url).status_code, 404)
        page = self.client.get(f"/library-preview/publications/{self.publication.pk}/recordings/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["recordings"], [])
        self.assertFalse(page.context["unavailable"])
        self.assertNotContains(page, media_fixture.TEXT)
        self.assertNotContains(page, "التسجيل أو التفريغ غير متاح الآن")
        self.privacy_grant("PUBLIC_MEDIA", self.recording["id"], "READ", public=True)
        self.assertEqual(self.client.get(self.audio_url, HTTP_RANGE="bytes=0-15").status_code, 206)
        self.assert_originals()

    def test_late_media_callback_discards_already_assembled_range_and_then_recovers(self):
        self.admit_known()
        original = media_views._file_response
        armed = False
        key = self.exact_grants[("PUBLIC_MEDIA", self.recording["id"], "READ")]

        def build_then_arm(*args, **kwargs):
            nonlocal armed
            result = original(*args, **kwargs)
            armed = True
            return result

        def late_callback(values):
            if armed:
                self.privacy_authority.grants.pop(key, None)

        self.rights.hook = late_callback
        with patch.object(media_views, "_file_response", side_effect=build_then_arm):
            response = self.client.get(self.audio_url, HTTP_RANGE="bytes=0-15")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Content-Range", response)
        self.assertNotIn(media_fixture.audio()[:16], response.content)
        self.rights.hook = None
        self.privacy_grant("PUBLIC_MEDIA", self.recording["id"], "READ", public=True)
        self.assertEqual(self.client.get(self.audio_url, HTTP_RANGE="bytes=0-15").status_code, 206)
        self.assert_originals()

    def test_privacy_callback_cannot_revoke_original_rights_and_leave_public_bytes(self):
        self.admit_known()
        original = self.privacy_authority.authorize

        def revoke_original(**values):
            result = original(**values)
            if values["target_kind"] == "PUBLIC_MEDIA" and values["action"] == "READ":
                self.rights.denied.add("publisher")
            return result

        with patch.object(self.privacy_authority, "authorize", side_effect=revoke_original):
            self.assertEqual(self.client.get(self.audio_url).status_code, 404)
        self.rights.denied.clear()
        self.assertEqual(self.client.get(self.audio_url, HTTP_RANGE="bytes=0-15").status_code, 206)
        self.assert_originals()
