"""Public READ never implicitly permits catalog/search/sitemap discovery."""

from unittest.mock import patch

from django.apps import apps
from django.test import TransactionTestCase, override_settings

from apps.public_collections import services as collections
from apps.public_collections import test_support as collection_fixture
from apps.public_collections import views as collection_views
from apps.public_knowledge import public as knowledge
from apps.public_knowledge import tests as knowledge_fixture
from apps.public_knowledge import views as knowledge_views
from apps.public_teaching import services as teaching
from apps.public_teaching import test_support as teaching_fixture
from apps.public_teaching import views as teaching_views

from .catalog import TARGETS
from .public_derivative_test_support import PrivacyAssertions


class SearchGrants(PrivacyAssertions):
    def admit_search(self):
        self.search_grants = {}
        for kind in (
            "PUBLICATION",
            "PUBLIC_KNOWLEDGE",
            "PUBLIC_COLLECTION",
            "PUBLIC_TEACHING",
            "LIBRARY_VERSION",
        ):
            for identifier in apps.get_model(TARGETS[kind][0]).objects.values_list("pk", flat=True):
                self.search_grants[(kind, str(identifier))] = self.privacy_grant(
                    kind, identifier, "SEARCH", public=True
                )

    def deny_search(self, kind, identifier):
        self.privacy_authority.grants.pop(self.search_grants[(kind, str(identifier))])

    def late_search_denial(self, module, authority, url, kind, identifier):
        armed = False
        render, permit = module.render, authority.permits
        key = self.search_grants[(kind, str(identifier))]

        def render_then_arm(*args, **kwargs):
            nonlocal armed
            response = render(*args, **kwargs)
            armed = True
            return response

        def last_callback(**values):
            result = permit(**values)
            if armed:
                self.privacy_authority.grants.pop(key, None)
            return result

        with (
            patch.object(module, "render", side_effect=render_then_arm),
            patch.object(authority, "permits", side_effect=last_callback),
        ):
            response = self.client.get(url)
        self.assertTrue(armed)
        self.assertEqual(response.status_code, 404)
        self.privacy_grant(kind, identifier, "SEARCH", public=True)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assert_originals()


@override_settings(**knowledge_fixture.FEATURES)
class KnowledgeDiscoveryTests(SearchGrants, knowledge_fixture.CurationFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.scholar, self.parent, self.child, self.presentation, self.translation = (
            self.published()
        )
        self.enable_privacy()
        self.admit_known()

    def test_index_and_sitemap_need_search_before_topics_dependencies_and_urls(self):
        page = self.client.get("/library-preview/knowledge/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["scholars"], [])
        self.assertEqual(page.context["topics"], [])
        self.assertEqual(self.page(self.scholar).status_code, 200)
        self.admit_search()
        topic_url = f"/library-preview/knowledge/topics/{self.child['series_id']}/"
        self.assertContains(self.client.get("/library-preview/knowledge/sitemap.xml"), topic_url)
        self.deny_search("PUBLIC_KNOWLEDGE", self.child["id"])
        with knowledge.projection(search=True) as result:
            self.assertEqual(len(result.topics), 1)
            self.assertEqual(result.presentations, {})
        self.assertNotContains(self.client.get("/library-preview/knowledge/sitemap.xml"), topic_url)
        self.assertEqual(self.client.get(topic_url).status_code, 200)
        self.deny_search("PUBLICATION", self.edition["id"])
        with knowledge.projection(search=True) as result:
            self.assertEqual(result.sources, {})
            self.assertEqual(result.records, {})
        self.assertEqual(self.page(self.scholar).status_code, 200)
        self.assert_originals()

    def test_late_search_revoke_discards_native_index_then_reads_again(self):
        self.admit_search()
        self.late_search_denial(
            knowledge_views,
            self.curation_authority,
            "/library-preview/knowledge/",
            "PUBLIC_KNOWLEDGE",
            self.scholar["id"],
        )


@override_settings(**collection_fixture.FEATURES)
class CollectionDiscoveryTests(
    SearchGrants, collection_fixture.CollectionFixture, TransactionTestCase
):
    def setUp(self):
        super().setUp()
        self.material = self.library_record(title="مادة مستقلة لا تكتشف دون إذن")
        members = [
            self.member(),
            f"LIBRARY|{self.material['version_id']}|{self.material['digest']}",
        ]
        self.parent = self.release_collection(self.create_collection(kind="TOPIC", members=members))
        self.child = self.release_collection(
            self.create_collection(
                kind="TOPIC",
                parent_id=self.parent["id"],
                members=members,
            )
        )
        self.enable_privacy()
        self.admit_known()

    def test_readable_collections_are_not_discoverable_until_exact_search_grants(self):
        page = self.client.get("/library-preview/collections/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["rows"], [])
        self.assertEqual(page.context["topics"], [])
        self.assertEqual(self.client.get(self.collection_url(self.child)).status_code, 200)
        self.admit_search()
        page = self.client.get("/library-preview/collections/")
        self.assertEqual(len(page.context["rows"]), 2)
        self.deny_search("PUBLIC_COLLECTION", self.parent["id"])
        page = self.client.get("/library-preview/collections/", {"kind": "TOPIC"})
        self.assertEqual(page.context["rows"], [])
        self.assertEqual(page.context["topics"], [])
        self.assertEqual(self.client.get(self.collection_url(self.child)).status_code, 200)
        self.assert_originals()

    def test_member_search_is_checked_before_its_title_enters_the_haystack(self):
        self.admit_search()
        with collections.public_projection() as rows:
            title = next(row["title"] for row in rows[0]["members"] if row["kind"] == "LIBRARY")
        self.assertEqual(
            len(self.client.get("/library-preview/collections/", {"q": title}).context["rows"]), 2
        )
        self.deny_search("LIBRARY_VERSION", self.material["version_id"])
        page = self.client.get("/library-preview/collections/", {"q": title})
        self.assertEqual(page.context["rows"], [])
        self.assertEqual(page.context["topics"], [])
        self.assertContains(self.client.get(self.collection_url(self.child)), title)
        self.privacy_grant("LIBRARY_VERSION", self.material["version_id"], "SEARCH", public=True)
        self.assertEqual(
            len(self.client.get("/library-preview/collections/", {"q": title}).context["rows"]), 2
        )
        self.assert_originals()

    def test_last_callback_rejects_already_filtered_collection_html(self):
        self.admit_search()
        self.late_search_denial(
            collection_views,
            self.collections_authority,
            "/library-preview/collections/",
            "PUBLIC_COLLECTION",
            self.parent["id"],
        )


@override_settings(**teaching_fixture.FEATURES)
class TeachingDiscoveryTests(SearchGrants, teaching_fixture.TeachingFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.released = self.complete()
        self.enable_privacy()
        self.admit_known()

    def test_catalog_search_is_separate_from_direct_lesson_and_series_reads(self):
        page = self.client.get("/library-preview/teaching/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["lessons"], [])
        self.assertEqual(page.context["series"], [])
        first = teaching.TeachingVersion.objects.get(pk=self.released["lessons"][0]["id"])
        lesson_url = f"/library-preview/teaching/lessons/{first.item.public_id}/"
        self.assertEqual(self.client.get(lesson_url).status_code, 200)
        self.admit_search()
        page = self.client.get("/library-preview/teaching/")
        self.assertEqual(len(page.context["lessons"]), 2)
        self.assertEqual(len(page.context["series"]), 1)
        self.deny_search("PUBLIC_TEACHING", first.pk)
        page = self.client.get("/library-preview/teaching/")
        self.assertEqual(len(page.context["lessons"]), 1)
        self.assertEqual(page.context["series"], [])
        self.assertNotIn(lesson_url, page.content.decode())
        self.assertEqual(self.client.get(lesson_url).status_code, 200)
        self.assert_originals()

    def test_source_material_search_is_not_inherited_from_its_attribution(self):
        self.admit_search()
        material = self.released["material"]
        self.deny_search("LIBRARY_VERSION", material.pk)
        page = self.client.get("/library-preview/teaching/")
        self.assertEqual(list(page.context["scholars"]), [])
        with teaching.public_projection() as current:
            self.assertTrue(list(current.catalog()["scholars"]))
        self.privacy_grant("LIBRARY_VERSION", material.pk, "SEARCH", public=True)
        page = self.client.get("/library-preview/teaching/")
        self.assertTrue(list(page.context["scholars"]))
        self.assert_originals()

    def test_last_source_callback_rejects_discovery_after_render(self):
        self.admit_search()
        self.late_search_denial(
            teaching_views,
            self.teaching_authority,
            "/library-preview/teaching/",
            "PUBLIC_TEACHING",
            self.released["lessons"][0]["id"],
        )
