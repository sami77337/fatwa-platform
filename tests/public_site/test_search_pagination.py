"""Homepage paging boundaries and privacy; synthetic service responses only."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from apps.reference.query import Page
from apps.reference.services import CatalogPage
from tests.public_site.test_pages import SOURCE, Elements


@override_settings(PUBLIC_SITE_ORIGIN="https://catalog.example")
class SearchPaginationTests(SimpleTestCase):
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
        self.search = self.enterContext(patch("apps.public_site.views.search"))
        self.search.return_value = CatalogPage([{"id": 31, "title": "عنوان"}], 61, 30, 30, 60)
        self.params = {"q": "عُنْوان & آمن", "mode": "literal", "depth": "2", "has_children": "false"}

    def test_next_previous_links_preserve_exact_query_and_filters(self):
        response = self.client.get("/", {**self.params, "offset": 30})
        self.search.assert_called_once_with(
            self.edition, self.params["q"], "literal", Page(30, 30), depth=2, has_children=False
        )
        links = {
            a.get("rel"): a["href"] for a in Elements(response.content).find("a") if a.get("rel")
        }
        for rel, offset in (("prev", None), ("next", "60")):
            parts = urlsplit(links[rel])
            self.assertEqual(
                (parts.scheme, parts.netloc, parts.path, parts.fragment),
                ("", "", "/", "results-title"),
            )
            expected = {k: [v] for k, v in self.params.items()}
            if offset:
                expected["offset"] = [offset]
            self.assertEqual(parse_qs(parts.query), expected)
        self.assertContains(response, "عرض النتائج 31–31")
        self.assertContains(response, '<ol start="31">')

    def test_first_and_last_pages_only_offer_valid_direction(self):
        for offset, total, next_offset, expected in (
            (0, 31, 30, {"next"}),
            (30, 31, None, {"prev"}),
            (0, 1, None, set()),
        ):
            self.search.return_value = CatalogPage(
                [{"id": 1, "title": "عنوان"}], total, 30, offset, next_offset
            )
            response = self.client.get("/", {"q": "عنوان", "offset": offset})
            self.assertEqual(
                {a["rel"] for a in Elements(response.content).find("a") if a.get("rel")}, expected
            )

    def test_empty_later_page_has_recovery_without_claiming_no_matches(self):
        self.search.return_value = CatalogPage([], 10, 30, 90, None)
        response = self.client.get("/", {"q": "عنوان", "offset": 90})
        self.assertContains(response, "لا توجد نتائج في هذه الصفحة")
        self.assertContains(response, "أول النتائج")
        self.assertNotContains(response, "لا توجد عناوين مطابقة")
        self.assertNotContains(response, "عرض النتائج")
        self.assertEqual(
            parse_qs(urlsplit(response.context["first_results_url"]).query),
            {"q": ["عنوان"], "mode": ["normalized"]},
        )

    def test_resubmitting_form_resets_offset(self):
        response = self.client.get("/", {**self.params, "offset": 30})
        document = Elements(response.content)
        self.assertEqual(document.find("form")[0]["action"], "/")
        self.assertNotIn("offset", {field.get("name") for field in document.find("input")})

    def test_invalid_offsets_and_query_keys_are_rejected_before_reads(self):
        queries = [
            {"q": "عنوان", "offset": value}
            for value in ("", "-1", "20001", "1.5", "٣٠", "9" * 100, ["0", "30"])
        ] + [{"offset": "30"}, {"q": "   ", "offset": "0"}, {"q": "عنوان", "token": "private"}]
        for query in queries:
            with self.subTest(query=query):
                response = self.client.get("/", query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response["X-Robots-Tag"], "noindex, nosnippet")
        self.books.assert_not_called()
        self.search.assert_not_called()

    def test_bounded_last_window_explains_remaining_results(self):
        self.search.return_value = CatalogPage(
            [{"id": 1, "title": "عنوان"}], 20050, 30, 20000, None
        )
        response = self.client.get("/", {"q": "عنوان", "offset": 20000})
        self.assertContains(response, "بلغت حد التصفح")
        self.assertNotContains(response, 'rel="next"')
        self.assertEqual(self.search.call_args.args[3], Page(30, 20000))

    def test_query_variants_have_no_preview_cache_or_referrer(self):
        for method in (self.client.get, self.client.head):
            response = method("/", {"q": "عبارة خاصة اصطناعية", "offset": 30})
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertEqual(response["X-Robots-Tag"], "noindex, nosnippet")
            document = Elements(response.content)
            self.assertFalse(
                [m for m in document.find("meta") if m.get("property", "").startswith("og:")]
            )
            self.assertFalse(
                [link for link in document.find("link") if link.get("rel") == "canonical"]
            )
            self.assertFalse(response.cookies)

    def test_later_page_outage_hides_partial_source_results_and_exception(self):
        self.search.side_effect = OperationalError("private-db-connection")
        response = self.client.get("/", {"q": "عنوان", "offset": 30})
        self.assertContains(response, "تعذر الوصول")
        self.assertNotContains(response, "private-db-connection")
        self.assertNotContains(response, SOURCE["work"]["title_original"])
        self.assertNotContains(response, "صفحات نتائج البحث")
