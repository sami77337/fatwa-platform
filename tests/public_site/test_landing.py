"""D5 synthetic-32-root-shape-v1: mocked output, not owner-source acceptance."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import OperationalError
from django.test import SimpleTestCase
from django.urls import resolve

from apps.reference.query import Page
from apps.reference.services import CatalogPage, CatalogUnavailable, HeadingNotFound
from tests.public_site.test_pages import SOURCE, Elements


class LandingTests(SimpleTestCase):
    def setUp(self):
        self.books = self.enterContext(
            patch(
                "apps.public_site.views.list_books",
                return_value=CatalogPage([SOURCE], 1, 1, 0, None),
            )
        )
        self.edition = object()
        self.resolver = self.enterContext(
            patch(
                "apps.public_site.views.resolve_edition",
                return_value=self.edition,
            )
        )
        # Shape only: two introductions plus thirty books; titles explicitly synthetic.
        self.rows = [
            {
                "id": n,
                "title": f"مقدمة اختبار {n}" if n <= 2 else f"كتاب اختبار {n}",
                "children_count": n,
            }
            for n in range(1, 33)
        ]
        self.roots = self.enterContext(
            patch(
                "apps.public_site.views.roots",
                return_value=CatalogPage(self.rows, 32, 100, 0, None),
            )
        )
        self.search = self.enterContext(
            patch(
                "apps.public_site.views.search",
                return_value=CatalogPage([], 0, 30, 0, None),
            )
        )

    def test_all_32_roots_in_source_order_including_introductions(self):
        response = self.client.get("/")
        self.assertEqual(response.context["roots"].items, self.rows)
        document = response.content.decode()
        positions = [document.index(row["title"]) for row in self.rows]
        self.assertEqual(positions, sorted(positions))
        for row in self.rows:
            self.assertContains(response, ">" + row["title"] + "</a>", count=1)

    def test_root_links_resolve_to_existing_heading_and_pin_source(self):
        anchors = Elements(self.client.get("/").content).find("a")
        links = [a["href"] for a in anchors if a["href"].startswith("/fiqh/nodes/")]
        self.assertEqual(len(links), 32)
        for n, href in enumerate(links, 1):
            match = resolve(urlsplit(href).path)
            self.assertEqual(match.url_name, "heading")
            self.assertEqual(match.kwargs, {"ident": n})
            self.assertEqual(
                parse_qs(urlsplit(href).query), {"basic": ["1"], "edition": [str(SOURCE["id"])]}
            )

    def test_bounded_reads_and_no_search_on_initial_load(self):
        self.client.get("/")
        self.books.assert_called_once_with(Page(1))
        self.resolver.assert_called_once_with(SOURCE["id"])
        self.roots.assert_called_once_with(self.edition, Page(100))
        self.search.assert_not_called()

    def test_counts_come_from_services(self):
        response = self.client.get("/")
        self.assertContains(response, "عدد الجذور: 32")
        self.assertContains(response, str(SOURCE["heading_count"]))

    def test_no_edition_control_or_publisher_clutter(self):
        response = self.client.get("/")
        controls = Elements(response.content).find("select")
        self.assertEqual({c["name"] for c in controls}, {"mode", "depth", "has_children"})
        for value in [SOURCE["publisher"], SOURCE["title"], SOURCE["edition_key"]]:
            self.assertNotContains(response, value)

    def test_root_titles_are_escaped_without_normalization(self):
        self.rows[0]["title"] = '<img src=x onerror="alert(1)"> أَصْل'
        response = self.client.get("/")
        self.assertContains(response, "&lt;img")
        self.assertContains(response, "أَصْل")
        self.assertFalse(Elements(response.content).find("img"))

    def test_search_with_all_filters_uses_existing_service(self):
        response = self.client.get(
            "/",
            {
                "q": "الطهارة",
                "mode": "literal",
                "depth": "3",
                "has_children": "false",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.search.assert_called_once_with(
            self.edition,
            "الطهارة",
            "literal",
            Page(30),
            depth=3,
            has_children=False,
        )
        selects = Elements(response.content).find("option")
        selected = {o["value"] for o in selects if "selected" in o}
        self.assertEqual(selected, {"literal", "3", "false"})

    def test_search_results_link_to_heading_and_escape_title(self):
        self.search.return_value = CatalogPage(
            [{"id": 99, "title": "<script>bad</script>"}],
            1,
            30,
            0,
            None,
        )
        response = self.client.get("/", {"q": "عنوان"})
        self.assertContains(response, 'href="/fiqh/nodes/99?basic=1&amp;edition=73"')
        self.assertContains(response, "&lt;script&gt;")
        self.assertFalse(Elements(response.content).find("script"))

    def test_empty_search_distinct_from_empty_storage(self):
        response = self.client.get("/", {"q": "غائب"})
        self.assertContains(response, "لا توجد عناوين مطابقة")
        self.assertNotContains(response, "لم يُحمّل")

    def test_invalid_queries_never_call_search(self):
        for query in [
            {"q": "x" * 161},
            {"q": "x " * 11},
            {"q": "x", "depth": "6"},
            {"q": "x", "has_children": "yes"},
            {"q": "x", "mode": "unknown"},
            {"q": ["x", "y"]},
            {"edition": "73"},
            {"q": "x\x00"},
            {"depth": "2"},
            {"has_children": "true"},
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/", query).status_code, 400)
        self.search.assert_not_called()

    def test_query_attribute_is_escaped(self):
        response = self.client.get("/", {"q": '"><img src=x>'})
        self.assertFalse(Elements(response.content).find("img"))
        self.assertContains(response, "&quot;&gt;&lt;img")

    def test_registered_source_without_roots_is_honest(self):
        self.roots.return_value = CatalogPage([], 0, 100, 0, None)
        response = self.client.get("/")
        self.assertContains(response, "لا توجد جذور محمّلة")
        self.assertNotContains(response, "32")

    def test_multiple_sources_do_not_resolve_or_read_roots(self):
        self.books.return_value = CatalogPage([SOURCE], 2, 1, 0, 1)
        response = self.client.get("/", {"q": "عنوان"})
        self.assertContains(response, "البحث المباشر معطّل")
        self.resolver.assert_not_called()
        self.roots.assert_not_called()
        self.search.assert_not_called()
        self.assertFalse(Elements(response.content).find("form"))

    def test_empty_storage_does_not_read_roots(self):
        self.books.return_value = CatalogPage([], 0, 1, 0, None)
        response = self.client.get("/")
        self.assertContains(response, "لم يُحمّل")
        self.resolver.assert_not_called()
        self.roots.assert_not_called()

    def test_failures_do_not_expose_partial_roots_or_source_details(self):
        for error in [OperationalError("secret"), CatalogUnavailable("secret")]:
            self.roots.side_effect = error
            response = self.client.get("/")
            self.assertContains(response, "تعذر الوصول")
            self.assertNotContains(response, "secret")
            self.assertNotContains(response, SOURCE["work"]["title_original"])
            self.assertFalse(Elements(response.content).find("form"))

    def test_edition_disappeared_between_reads(self):
        self.resolver.side_effect = HeadingNotFound("secret")
        self.assertContains(self.client.get("/"), "تعذر الوصول")
        self.roots.assert_not_called()

    def test_help_explains_filters_and_citation_without_reads(self):
        response = self.client.get("/help")
        for text in ["عمق العنوان", "بلا عناوين فرعية", "الطهارة", "لا تخمّن", "وليست فتاوى منشورة"]:
            self.assertContains(response, text)
        self.books.assert_not_called()

    def test_mobile_keyboard_landmarks_and_labels_for_every_control(self):
        document = Elements(self.client.get("/").content)
        labels = {label["for"] for label in document.find("label")}
        for control in document.find("input") + document.find("select"):
            self.assertIn(control["id"], labels)
        self.assertEqual(len(document.find("main")), 1)
        self.assertEqual(len(document.find("h1")), 1)
        self.assertEqual(document.find("html"), [{"lang": "ar", "dir": "rtl"}])
        self.assertTrue(any(m.get("name") == "viewport" for m in document.find("meta")))
        self.assertFalse(document.find("script"))
