"""Opt-in title ranking uses existing browser-bound search/open/back navigation."""

from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.arabic_search_eval.test_services import search_fixture
from apps.casework.models import Case
from apps.reference.models import ReferenceHeading
from apps.research_workspace.tests import SETTINGS, ResearchFixture
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority
from tests.casework.test_http import WEB_SETTINGS, hidden, post


@override_settings(**{
    **SETTINGS, **WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_SOURCE_RIGHTS_ENABLED": True, "FATWA_ARABIC_SEARCH_EVAL_ENABLED": True,
})
class SearchUiTests(ResearchFixture, TransactionTestCase):
    def setUp(self):
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False), patch(
            "apps.knowledge_links.tests.source_fixture", side_effect=search_fixture
        ):
            super().setUp()
        overlay = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.grants = []
        for row in (2, 3):
            heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=row)
            source = rights.register(**self.common, kind="TOC_METADATA", target_id=heading.pk)
            grant = rights.propose(**self.common, source_id=source["id"], expected_number=0,
                                   uses=["READ", "CITE"], basis="synthetic", note="synthetic", ttl_minutes=30)
            rights.review(**{**self.common, "subject_id": "publisher"}, revision_id=grant["id"],
                          action="APPROVE", confirmed=True, note="synthetic independent review")
            self.grants.append(grant)
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = self.client.get("/casework/staff/login/")
        post(self.client, "/casework/staff/login/", {"credential": "synthetic-editor-credential-32-characters"}, page)
        self.page = self.client.get("/casework/staff/")

    def search(self, **updates):
        return post(self.client, "/casework/staff/", {
            "action": "research_search", "case_ref": self.receipt["public_ref"],
            "query": "رقم ١٢", "kind": "REFERENCE", "edition_id": str(self.catalog_id),
            "printed_part": "", "printed_page": "", "ranking": "evaluated_titles", **updates,
        }, self.page)

    def test_ranked_search_open_back_preserves_scope_filters_and_canonical_answer(self):
        before = Case.objects.get(pk=self.receipt["case_id"]).revision
        page = self.search()
        self.assertContains(page, "عنوان رقم 12")
        self.assertNotContains(page, "عنوان رقم 112")
        self.assertContains(page, 'id="research-ranking-scope"')
        self.assertContains(page, f'value="{self.catalog_id}" selected')
        state = hidden(page, "state")
        opened = post(self.client, "/casework/staff/", {
            "action": "research_view", "case_ref": self.receipt["public_ref"], "state": state,
        }, page)
        self.assertContains(opened, "عنوان فهرس موثق فقط")
        back = post(self.client, "/casework/staff/", {
            "action": "research_back", "case_ref": self.receipt["public_ref"], "state": hidden(opened, "state"),
        }, opened)
        self.assertContains(back, 'value="رقم ١٢"')
        self.assertContains(back, 'id="research-ranking-scope"')
        self.assertEqual(Case.objects.get(pk=self.receipt["case_id"]).revision, before)

    def test_flag_strict_kind_and_revoked_source_do_not_fallback(self):
        for options in ({"FATWA_ARABIC_SEARCH_EVAL_ENABLED": False}, {"FATWA_SOURCE_RIGHTS_ENFORCED": False}):
            with override_settings(**options):
                self.assertEqual(self.search().status_code, 409)
        self.assertEqual(self.search(kind="all").status_code, 400)
        self.assertEqual(self.search(ranking="unreviewed_mode").status_code, 400)
        page = self.search()
        state = hidden(page, "state")
        rights.review(**{**self.common, "subject_id": "publisher"}, revision_id=self.grants[0]["id"],
                      action="REVOKE", confirmed=True, note="synthetic revocation")
        reopened = post(self.client, "/casework/staff/", {
            "action": "research_view", "case_ref": self.receipt["public_ref"], "state": state,
        }, page)
        self.assertEqual(reopened.status_code, 409)
        self.assertNotContains(reopened, "عنوان رقم 12", status_code=409)
