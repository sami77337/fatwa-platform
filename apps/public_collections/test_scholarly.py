"""Collections over actual independently released scholar and lesson versions."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.public_knowledge.test_scholarly import IntegratedFixture

from . import views
from .test_support import FEATURES, CollectionFixture

INTEGRATED = {**FEATURES, "FATWA_SCHOLARLY_LINKS_ENABLED": True, "FATWA_ANSWER_MEDIA_ENABLED": True}


class CombinedFixture(IntegratedFixture, CollectionFixture):
    def setUp(self):
        super().setUp()
        self.collections_authority.refs.add(self.second["public_ref"])
        self.library_authority.refs.add(self.second["public_ref"])


@override_settings(**INTEGRATED)
class ScholarlyCollectionTests(CombinedFixture, TransactionTestCase):
    def selected_materials(self):
        scholar = self.release_record(self.save_record())
        presentation = self.presentation()
        version, link = self.lesson()
        lesson = self.release_record(self.lesson_record(version))
        members = [
            self.member(),
            f"SCHOLAR|{scholar['id']}|{scholar['sha256']}",
            f"LESSON|{lesson['id']}|{lesson['sha256']}",
            f"PRESENTATION|{presentation['id']}|{presentation['sha256']}",
        ]
        row = self.release_collection(self.create_collection(kind="HOME", members=members))
        return row, link

    def test_curated_home_links_real_scholars_lessons_and_publications(self):
        row, _ = self.selected_materials()
        response = self.client.get("/library-preview/collections/")
        self.assertContains(response, "علماء")
        self.assertContains(response, "دروس")
        self.assertContains(response, "عالم تجريبي")
        self.assertContains(response, "درس مصرح بعرضه")
        self.assertNotContains(response, "PRIVATE")
        self.assertNotContains(response, str(self.part.pk))
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 200)

    def test_underlying_lesson_withdrawal_during_collection_render_is_closed(self):
        row, link = self.selected_materials()
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.review_link(link, "WITHDRAW")
            return response

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client.get(self.collection_url(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "درس مصرح بعرضه", status_code=404)
