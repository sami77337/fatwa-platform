"""D4 SSR routing with synthetic service responses; no database writes/connections."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.reference import services
from apps.reference.query import Page
from tests.integration.api.test_catalog import edition


class D4FilterUITests(SimpleTestCase):
    def test_ssr_filters_and_bookmark_pagination(self):
        source = edition()
        inventory = services.CatalogPage([services.edition_data(source)], 1, 100, 0, None)
        results = services.CatalogPage([], 42, 20, 20, 40)
        for depth in range(1, 6):
            for children in ["true", "false", ""]:
                with (
                    self.subTest(depth=depth, children=children),
                    patch("apps.reference.services.list_books", return_value=inventory),
                    patch("apps.reference.services.resolve_edition", return_value=source),
                    patch("apps.reference.services.search", return_value=results) as search,
                ):
                    response = self.client.get(
                        "/fiqh",
                        {
                            "basic": "1",
                            "edition": "7",
                            "q": "  عنوان & بحث  ",
                            "mode": "exact",
                            "limit": "20",
                            "offset": "20",
                            "depth": str(depth),
                            "has_children": children,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    search.assert_called_once_with(
                        source,
                        "  عنوان & بحث  ",
                        "exact",
                        Page(20, 20),
                        None,
                        depth=depth,
                        has_children=None if not children else children == "true",
                    )
                    html = response.content.decode()
                    self.assertIn('id="basic-depth"', html)
                    self.assertIn("جميع المستويات", html)
                    self.assertIn("العناوين الفرعية", html)
                    self.assertIn("بلا عناوين فرعية", html)
                    self.assertIn('id="basic-has_children"', html)
                    self.assertIn("offset=40", html)
                    self.assertIn("depth=" + str(depth), html)
                    self.assertIn("%26", html)
                    self.assertNotIn("reference/catalog.js", html)
                    self.assertNotIn(source.title, html)
                    if children:
                        self.assertIn("has_children=" + children, html)

    def test_invalid_ssr_filters_fail_before_database_access(self):
        for query in [
            "depth=6",
            "depth=0",
            "depth=x",
            "depth=2&depth=3",
            "has_children=False",
            "has_children=null",
            "offset=20001",
        ]:
            self.assertEqual(self.client.get("/fiqh?basic=1&" + query).status_code, 400)

    def test_default_roots_head_errors_and_methods(self):
        source = edition()
        inventory = services.CatalogPage([services.edition_data(source)], 1, 100, 0, None)
        results = services.CatalogPage([], 0, 30, 0, None)
        with (
            patch("apps.reference.services.list_books", return_value=inventory),
            patch("apps.reference.services.resolve_edition", return_value=source),
            patch("apps.reference.services.roots", return_value=results) as roots,
            patch("apps.reference.services.search") as search,
        ):
            self.assertEqual(self.client.get("/fiqh").status_code, 200)
            self.assertEqual(self.client.head("/fiqh?basic=1").content, b"")
            roots.assert_called_with(source, Page())
            search.assert_not_called()
        with patch("apps.reference.services.list_books", side_effect=services.CatalogUnavailable):
            self.assertEqual(self.client.get("/fiqh?basic=1&q=عنوان").status_code, 503)
        self.assertEqual(self.client.post("/fiqh?basic=1").status_code, 405)

    def test_ambiguous_source_still_requires_explicit_identity(self):
        inventory = services.CatalogPage(
            [services.edition_data(edition(7)), services.edition_data(edition(8))], 2, 100, 0, None
        )
        with patch("apps.reference.services.list_books", return_value=inventory):
            self.assertEqual(self.client.get("/fiqh?basic=1&q=عنوان&depth=2").status_code, 400)
