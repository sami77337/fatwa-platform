"""The public index and source guide expose fixed, query-independent metadata."""

from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from apps.reference.services import CatalogPage
from tests.public_site.test_pages import SOURCE, Elements


@override_settings(PUBLIC_SITE_ORIGIN="https://catalog.example")
class PublicMetadataTests(SimpleTestCase):
    def setUp(self):
        self.books = self.enterContext(
            patch("apps.public_site.views.list_books", return_value=CatalogPage([], 0, 1, 0, None))
        )

    def metadata(self, response):
        document = Elements(response.content)
        urls = [a["href"] for a in document.find("link") if a.get("rel") == "canonical"]
        graph = [
            (a["property"], a["content"])
            for a in document.find("meta")
            if a.get("property", "").startswith("og:")
        ]
        self.assertEqual(len(graph), len(dict(graph)))
        return urls, dict(graph)

    def test_each_public_page_has_its_own_fixed_address_and_arabic_description(self):
        for path, title in [
            ("/", "الرئيسية | الفهرس الفقهي"),
            ("/help", "دليل الاستخدام والمصدر | الفهرس الفقهي"),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                urls, graph = self.metadata(response)
                self.assertEqual(urls, ["https://catalog.example" + path])
                (description,) = [
                    m["content"]
                    for m in Elements(response.content).find("meta")
                    if m.get("name") == "description"
                ]
                self.assertTrue(description.strip())
                self.assertEqual(
                    graph,
                    {
                        "og:url": urls[0],
                        "og:title": title,
                        "og:description": description,
                        "og:type": "website",
                    },
                )
                self.assertContains(response, "<title>" + title + "</title>")

    @override_settings(ALLOWED_HOSTS=["localhost", "other.example"])
    def test_guide_alias_never_uses_request_origin_query_or_forwarded_headers(self):
        expected = self.metadata(self.client.get("/help", HTTP_HOST="localhost"))
        response = self.client.get(
            "/help?token=private-fixture",
            HTTP_HOST="other.example",
            HTTP_X_FORWARDED_HOST="elsewhere.example",
            HTTP_X_FORWARDED_PROTO="http",
        )
        self.assertEqual(self.metadata(response), expected)
        self.assertEqual(expected[0], ["https://catalog.example/help"])
        self.assertNotContains(response, "private-fixture")

    def test_search_and_invalid_input_do_not_generate_share_metadata(self):
        for path, code in [("/?q=private-fixture", 200), ("/?invalid=1", 400)]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, code)
                self.assertEqual(self.metadata(response), ([], {}))
                self.assertContains(
                    response, '<meta name="robots" content="noindex">', status_code=code
                )

    def test_search_results_on_loaded_catalog_stay_out_of_metadata(self):
        self.books.return_value = CatalogPage([SOURCE], 1, 1, 0, None)
        with (
            patch("apps.public_site.views.resolve_edition", return_value=object()),
            patch("apps.public_site.views.roots", return_value=CatalogPage([], 0, 100, 0, None)),
            patch(
                "apps.public_site.views.search", return_value=CatalogPage([], 0, 30, 0, None)
            ) as search,
        ):
            response = self.client.get("/", {"q": "عبارة خاصة اصطناعية"})
        search.assert_called_once()
        self.assertEqual(self.metadata(response), ([], {}))
        self.assertContains(response, '<meta name="robots" content="noindex">')

    def test_unavailable_catalog_suppresses_share_metadata(self):
        self.books.side_effect = OperationalError("internal-failure-fixture")
        response = self.client.get("/")
        self.assertEqual(self.metadata(response), ([], {}))
        self.assertNotContains(response, "internal-failure-fixture")
        self.assertContains(response, '<meta name="robots" content="noindex">')

    def test_unset_or_invalid_canonical_origin_never_yields_an_absolute_url(self):
        values = [
            None,
            "",
            "http://catalog.example",
            "//catalog.example",
            "https://u:p@catalog.example",
            "https://catalog.example/asset",
            "https://catalog.example?q=1",
            "https://catalog.example#x",
            "https://catalog.example\\@attacker.example",
            "https://catalog.example\n",
            "https://[broken",
            "https://catalog.example:65536",
            "https://catalog.example:0",
            "https://catalog.example//",
        ]
        for origin in values:
            with self.subTest(origin=origin), self.settings(PUBLIC_SITE_ORIGIN=origin):
                response = self.client.get("/help")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.metadata(response), ([], {}))
                self.assertNotContains(response, 'name="robots"')

    def test_default_clean_pages_keep_their_existing_indexing_behavior(self):
        with self.settings(PUBLIC_SITE_ORIGIN=None):
            for path in ["/", "/help"]:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(self.metadata(response), ([], {}))
                    self.assertNotContains(response, 'name="robots"')
                    self.assertContains(response, '<meta name="description"')
