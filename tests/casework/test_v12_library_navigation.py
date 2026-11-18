"""One authorized library collection and native publication/material return path."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.experimental_publication import tests_ui as publication_ui
from apps.knowledge_links import services as knowledge
from apps.source_rights import services as rights
from apps.source_rights.tests import ENABLED, RightsFixture
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(**{
    **WEB_SETTINGS, **ENABLED, "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_SOURCE_RIGHTS_ENFORCED": False, "FATWA_MUFTI_WORKSPACE_ENABLED": True,
})
class LibraryNavigationTests(RightsFixture, TransactionTestCase):
    login = publication_ui.PublicationContinuityTests.login

    def setUp(self):
        super().setUp()
        self.rights_grant = self.allow()
        self.approve(self.propose())
        overlay = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.library = {key: value for key, value in self.common.items() if key != "case_id"}

    def submit(self, client, page, action):
        fields = next(row for row in publication_ui.Forms(page.content.decode()).forms if row.get("action") == action)
        response = post(client, "/casework/staff/", fields, page)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response

    def test_source_metadata_search_and_collection_facets_use_current_rights(self):
        result = publication.library_catalog(**self.library, query=self.heading.title_original)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["categories"], [self.edition["category"]])
        self.assertEqual([row["id"] for row in result["publications"]], [self.edition["id"]])
        self.decision(self.rights_grant, "REVOKE")
        result = publication.library_catalog(**self.library, query=self.heading.title_original)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["publications"], [])
        self.assertEqual(result["categories"], [])

    def test_page_bounds_and_empty_page_do_not_invent_results(self):
        result = publication.library_catalog(**self.library, page=2)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["publications"], [])
        self.assertTrue(result["has_previous"])
        self.assertFalse(result["has_next"])
        for page in (True, 0, 101, "2"):
            with self.subTest(page=page), self.assertRaises(cases.CaseConflict):
                publication.library_catalog(**self.library, page=page)

    def test_one_catalog_call_and_native_material_roundtrip_keep_filters(self):
        client, page = self.login()
        with patch.object(publication, "library_catalog", wraps=publication.library_catalog) as read:
            page = post(client, "/casework/staff/", {
                "action": "pub_library", "query": self.heading.title_original,
                "category": self.edition["category"], "page": "1",
            }, page)
        self.assertEqual(page.status_code, 200, page.content[:300])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(page.context["total"], 1)
        page = self.submit(client, page, "pub_read")
        self.assertEqual(page.context["mufti_workspace"]["case"]["case_id"], self.receipt["case_id"])
        page = self.submit(client, page, "knowledge_browse")
        self.assertEqual(page.context["mufti_workspace"]["case"]["case_id"], self.receipt["case_id"])
        self.assertEqual(page.context["library_query"], self.heading.title_original)
        self.assertEqual(page.context["library_category"], self.edition["category"])
        page = self.submit(client, page, "knowledge_open")
        self.assertEqual(page.context["mufti_workspace"]["case"]["case_id"], self.receipt["case_id"])
        self.assertContains(page, self.heading.title_original)
        page = self.submit(client, page, "pub_read")
        self.assertEqual(page.context["query"], self.heading.title_original)
        self.assertEqual(page.context["category"], self.edition["category"])
        self.assertEqual(page.context["page"], 1)
        page = self.submit(client, page, "pub_library")
        self.assertEqual(page.context["total"], 1)
        self.assertEqual(page.context["query"], self.heading.title_original)

    def test_return_context_is_not_authority_and_rechecks_revoked_source(self):
        client, page = self.login()
        payload = {"action": "knowledge_browse", "publication_id": self.edition["id"],
                   "query": "", "library_query": "حفظ البحث", "library_category": "",
                   "library_page": "2"}
        response = post(client, "/casework/staff/", payload, page)
        self.assertEqual(response.status_code, 200)
        for injected in ({"case_ref": self.receipt["public_ref"]},
                         {"knowledge_authorized_case_ref": self.receipt["public_ref"]},
                         {"library_page": "101"}):
            with self.subTest(injected=injected):
                denied = post(client, "/casework/staff/", {**payload, **injected}, response)
                self.assertEqual(denied.status_code, 400)
        self.decision(self.rights_grant, "REVOKE")
        denied = post(client, "/casework/staff/", payload, response)
        self.assertEqual(denied.status_code, 404)
        self.assertNotContains(denied, self.heading.title_original, status_code=404)
        with self.assertRaises(cases.CaseConflict):
            knowledge.browse(**self.access)

    def test_clock_expiry_during_catalog_filtering_never_keeps_counts_or_facets(self):
        short = rights.propose(
            **self.common, source_id=self.source["id"], expected_number=1,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="Synthetic current grant", note="Synthetic", ttl_minutes=1,
        )
        self.decision(short)
        self.assertEqual(publication.library_catalog(**self.library)["total"], 1)
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)
        normalize = publication.normalize_editorial_search

        def delayed(value):
            result = normalize(value)
            if value.startswith(self.edition["title"] + " "):
                clock[0] = future
            return result

        with (patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
              patch.object(publication, "normalize_editorial_search", side_effect=delayed)):
            with self.assertRaises(cases.CaseConflict):
                publication.library_catalog(**self.library)
