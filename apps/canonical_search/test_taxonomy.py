"""PostgreSQL and native request regressions for reviewed taxonomy search.

These synthetic cases and provisional taxonomy labels are not scientific
quality evidence or an approved global fiqh classification.
"""
import re
from html import unescape
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.canonical_search import services as canonical
from apps.development_taxonomy.models import Concept, TreeVersion
from apps.development_taxonomy.test_support import FEATURES, TaxonomyFixture
from apps.canonical_search.test_support import FixtureAuthority, KnowledgeAuthority
from apps.research_workspace.tests import SyntheticRights
from tests.casework.test_http import post


@override_settings(**FEATURES)
class ReviewedTaxonomySearchTests(TaxonomyFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        ref = self.receipt["public_ref"]
        self.search_authority = FixtureAuthority(ref)
        features = override_settings(
            FATWA_CANONICAL_SEARCH_ENABLED=True,
            FATWA_CANONICAL_SEARCH_AUTHORITY=self.search_authority,
            FATWA_RESEARCH_WORKSPACE_ENABLED=True,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SyntheticRights(ref),
            FATWA_KNOWLEDGE_LINKS_ENABLED=True,
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=KnowledgeAuthority(ref),
        )
        features.enable()
        self.addCleanup(features.disable)
        self.version = self.review(self.save())
        self.bind(self.version)
        self.nodes = TreeVersion.objects.get(pk=self.version["id"]).nodes
        case = Case.objects.get(pk=self.receipt["case_id"])
        canonical.rebuild(
            **self.common,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_generation=0,
            request_key=uuid4(),
        )

    def find(self, node=1, *, version=None, children=False):
        return canonical.search(
            **self.common,
            value="اصطناعي",
            scope="CASE",
            taxonomy_version=(version or self.version)["id"],
            taxonomy_node=self.nodes[node]["id"],
            taxonomy_children=children,
        )

    def draft_nodes(self):
        definitions = {
            str(pk): definition
            for pk, definition in Concept.objects.filter(
                tree_id=self.version["tree_id"]
            ).values_list("id", "definition")
        }
        return [
            {
                "key": item["id"],
                "parent": item["parent"] or "",
                "name": item["name"],
                "definition": definitions[item["id"]],
            }
            for item in self.nodes
        ]

    def test_subtree_primary_additional_and_no_root_leak(self):
        self.assertGreater(self.find(1)["total"], 0)
        self.assertGreater(self.find(3)["total"], 0)
        self.assertEqual(self.find(0)["total"], 0)
        subtree = self.find(0, children=True)
        self.assertGreater(subtree["total"], 0)
        self.assertEqual(subtree["taxonomy"]["node_id"], self.nodes[0]["id"])
        self.assertTrue(subtree["taxonomy"]["children"])

    def test_exact_version_without_silent_migration(self):
        newer = self.review(self.save(nodes=self.draft_nodes(), tree=self.version))
        self.assertEqual(self.find(1, version=newer)["total"], 0)
        self.assertGreater(self.find(1)["total"], 0)

    def test_unreviewed_version_and_denied_tree_cannot_filter(self):
        pending = self.save(nodes=self.draft_nodes(), tree=self.version)
        with self.assertRaises(cases.CaseConflict):
            self.find(1, version=pending)
        self.authority.denied.add("SEARCH")
        with self.assertRaises(cases.CaseConflict):
            self.find(1)
        # The established text-only search does not borrow taxonomy rights.
        self.assertGreater(canonical.search(**self.common, value="اصطناعي")["total"], 0)

    def test_late_revocation_rejects_whole_response(self):
        original = canonical.search_in_context

        def after_results(*args, **kwargs):
            value = original(*args, **kwargs)
            self.authority.denied.add("SEARCH")
            return value

        with patch.object(canonical, "search_in_context", side_effect=after_results):
            with self.assertRaises(cases.CaseConflict):
                self.find(1)

    def test_native_signed_filter_and_form_denials(self):
        client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1",
            HTTP_HOST="127.0.0.1",
        )
        login = client.get("/casework/staff/login/")
        logged = post(
            client, "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"}, login,
        )
        self.assertEqual(logged.status_code, 303)
        page = client.get("/casework/staff/")
        page = post(
            client, "/casework/staff/",
            {"action": "cs_open", "case_ref": self.receipt["public_ref"]}, page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        fields = {
            "action": "cs_taxonomy_search",
            "case_ref": self.receipt["public_ref"],
            "query": "اصطناعي",
            "mode": "FTS",
            "kind": "ALL",
            "scope": "CASE",
            "page": "1",
            "taxonomy_version": self.version["id"],
            "taxonomy_node": self.nodes[1]["id"],
            "taxonomy_children": "1",
        }
        bad = post(
            client, "/casework/staff/",
            {**fields, "taxonomy_children": "invalid"}, page,
        )
        self.assertEqual(bad.status_code, 400)
        found = post(client, "/casework/staff/", fields, page)
        self.assertEqual(found.status_code, 200, found.content)
        self.assertContains(found, "canonical-taxonomy-scope")
        self.assertGreater(found.context["result"]["total"], 0)
        match = re.search(
            r'value="cs_source".*?name="state" value="([^"]+)"',
            found.content.decode(), re.S,
        )
        self.assertIsNotNone(match)
        opened = post(
            client, "/casework/staff/",
            {
                "action": "cs_source",
                "case_ref": self.receipt["public_ref"],
                "state": unescape(match.group(1)),
            },
            found,
        )
        self.assertEqual(opened.status_code, 200, opened.content)
        self.authority.denied.add("SEARCH")
        denied = post(client, "/casework/staff/", fields, opened)
        self.assertEqual(denied.status_code, 409)
        self.assertNotContains(
            denied, "سؤال اصطناعي لتصنيف مستقل", status_code=409,
        )
