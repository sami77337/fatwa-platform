"""Scoped browsing without new publication routes or access to private cases."""

from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceHeading
from apps.reference.query import Page
from apps.reference.services import CatalogPage, HeadingNotFound
from tests.public_site.section_fixture import seed_sections
from tests.public_site.test_pages import SOURCE, Elements


@override_settings(PUBLIC_SITE_ORIGIN="https://catalog.example")
class SectionBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.books = self.enterContext(
            patch(
                "apps.public_site.views.list_books",
                return_value=CatalogPage([SOURCE], 1, 1, 0, None),
            )
        )
        self.edition = object()
        self.enterContext(
            patch("apps.public_site.views.resolve_edition", return_value=self.edition)
        )
        self.enterContext(
            patch("apps.public_site.views.roots", return_value=CatalogPage([], 0, 100, 0, None))
        )
        self.node = self.enterContext(
            patch(
                "apps.public_site.views.node",
                return_value=SimpleNamespace(parent_id=None, depth=1, title_original="باب اصطناعي"),
            )
        )
        self.search = self.enterContext(
            patch(
                "apps.public_site.views.search",
                return_value=CatalogPage([{"id": 1, "title": "باب اصطناعي"}], 61, 30, 0, 30),
            )
        )

    def test_blank_query_browses_explicit_root_and_preserves_scope_in_links(self):
        response = self.client.get("/", {"root": "001", "depth": "2", "has_children": "false"})
        self.assertEqual(response.status_code, 200)
        self.node.assert_called_once_with(self.edition, 1)
        self.search.assert_called_once_with(
            self.edition, "", "normalized", Page(30), depth=2, has_children=False, root_id=1
        )
        self.assertEqual(
            parse_qs(urlsplit(response.context["next_results_url"]).query),
            {
                "root": ["1"],
                "mode": ["normalized"],
                "depth": ["2"],
                "has_children": ["false"],
                "offset": ["30"],
            },
        )
        self.assertEqual(response.context["all_sections_url"], "/")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nosnippet")
        self.assertNotContains(response, 'rel="canonical"')

    def test_clearing_scope_preserves_search_and_filters_and_resets_offset(self):
        response = self.client.get(
            "/", {"root": 1, "q": "أصل & عنوان", "mode": "literal", "depth": 2, "offset": 30}
        )
        params = parse_qs(urlsplit(response.context["all_sections_url"]).query)
        self.assertEqual(params, {"q": ["أصل & عنوان"], "mode": ["literal"], "depth": ["2"]})

    def test_invalid_root_numbers_or_duplicates_never_read_storage(self):
        for value in ("-1", "0", "1.5", "١", str(2**63), "9" * 100, ["1", "2"]):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/", {"root": value}).status_code, 400)
        self.books.assert_not_called()
        self.node.assert_not_called()
        self.search.assert_not_called()

    def test_unknown_or_nonroot_id_rejected_without_search_or_internal_details(self):
        for value in (
            HeadingNotFound("secret internal path"),
            SimpleNamespace(parent_id=99, depth=2, title_original="secret-child"),
        ):
            self.node.side_effect = value if isinstance(value, Exception) else None
            self.node.return_value = value
            response = self.client.get("/", {"root": 999})
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, "secret", status_code=400)
        self.search.assert_not_called()

    def test_valid_root_beyond_first_root_page_remains_selected_and_escaped(self):
        self.node.return_value.title_original = '<img src=x onerror="x"> أَصْل'
        response = self.client.get("/", {"root": 111})
        options = Elements(response.content).find("option")
        self.assertIn({"value": "111", "selected": None}, options)
        self.assertFalse(Elements(response.content).find("img"))
        self.assertContains(response, "&lt;img")
        self.assertContains(response, "أَصْل")

    def test_multiple_sources_still_refuse_implicit_scope(self):
        self.books.return_value = CatalogPage([SOURCE], 2, 1, 0, 1)
        response = self.client.get("/", {"root": 1})
        self.assertContains(response, "البحث المباشر معطّل")
        self.node.assert_not_called()
        self.search.assert_not_called()


class SectionJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Real PostgreSQL 17 or 18 required")
        cls.edition_id = seed_sections()

    def read(self, path="/", params=None):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, params)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 12)
        self.assertTrue(all(row["sql"].lstrip().startswith("SELECT") for row in queries))
        for row in queries:
            for forbidden in ("casework", "requester_tracking", "editorial"):
                self.assertNotIn(forbidden, row["sql"])
        return response

    def test_browse_all_depths_across_pages_without_other_root_or_mutation(self):
        before = list(ReferenceHeading.objects.order_by("pk").values())
        response = self.read(params={"root": 1})
        seen = []
        for count in (30, 30, 5):
            self.assertEqual(len(response.context["results"].items), count)
            seen += [row["id"] for row in response.context["results"].items]
            if response.context["next_results_url"]:
                response = self.read(response.context["next_results_url"])
        self.assertEqual(seen, list(range(1, 66)))
        self.assertFalse(response.context["next_results_url"])
        self.assertEqual(before, list(ReferenceHeading.objects.order_by("pk").values()))
        self.assertEqual(
            self.read(response.context["previous_results_url"]).context["results"].offset, 30
        )

    def test_keyword_scope_and_clear_scope_change_only_expected_results(self):
        response = self.read(params={"root": 1, "q": "عنوان مشترك", "depth": 2})
        self.assertEqual(response.context["results"].total, 61)
        unscoped = self.read(response.context["all_sections_url"])
        self.assertEqual(unscoped.context["results"].total, 62)
        other = self.read(params={"root": 100, "q": "عنوان مشترك"})
        self.assertEqual([row["id"] for row in other.context["results"].items], [101])

    def test_deep_filter_and_details_use_source_pinned_navigation(self):
        response = self.read(params={"root": 1, "depth": 5, "has_children": "false"})
        self.assertEqual([row["id"] for row in response.context["results"].items], [65])
        detail_url = next(
            a["href"]
            for a in Elements(response.content).find("a")
            if a["href"].startswith("/fiqh/nodes/65?")
        )
        self.assertEqual(
            parse_qs(urlsplit(detail_url).query),
            {"basic": ["1"], "edition": [str(self.edition_id)]},
        )
        detail = self.read(detail_url)
        self.assertContains(detail, "فرع خامس")
        self.assertContains(detail, "باب أول اصطناعي")

    def test_unknown_nonroot_and_private_writes_remain_closed(self):
        for root in (2, 999999):
            response = self.client.get("/", {"root": root})
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, "عنوان مشترك", status_code=400)
        self.assertEqual(self.client.post("/", {"root": 1}).status_code, 405)
        self.assertEqual(self.client.get("/fatwas").status_code, 404)
