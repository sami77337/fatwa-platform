"""Wave6 E4 regressions. No database access; real services compile PostgreSQL SQL."""

from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from html import escape
from html.parser import HTMLParser

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.reference import services, views
from apps.reference.query import Page
from tests.integration.api.test_catalog import cursor_rows, edition, heading, values


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.hrefs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href")


class E4CatalogTests(SimpleTestCase):
    def test_filter_only_search_executes_predicates_in_all_modes(self):
        row = heading(2, 1, 2)
        for mode in ("normalized", "literal", "exact"):
            for text in ("", "   "):
                with self.subTest(mode=mode, text=text), cursor_rows([(1,)], [values(row)]) as sql:
                    result = services.search(
                        edition(), text, mode, Page(1), depth=2, has_children=False
                    )
                    self.assertEqual([item["id"] for item in result.items], [2])
                self.assertEqual(len(sql.calls), 2)
                self.assertNotIn("LIKE", sql.calls[-1][0])
                self.assertNotIn(text, sql.calls[-1][1])

    def test_filter_only_ssr_calls_search_and_preserves_paging(self):
        source = edition()
        inventory = services.CatalogPage([services.edition_data(source)], 1, 100, 0, None)
        result = services.CatalogPage([], 5, 1, 1, 2)
        for mode in ("normalized", "literal", "exact"):
            with (
                self.subTest(mode=mode),
                patch.object(services, "list_books", return_value=inventory),
                patch.object(services, "resolve_edition", return_value=source),
                patch.object(services, "search", return_value=result) as search,
                patch.object(services, "roots", return_value=result) as roots,
            ):
                response = self.client.get("/fiqh", {
                    "edition": 7, "q": "", "mode": mode, "root": 1,
                    "depth": 2, "has_children": "false", "limit": 1, "offset": 1,
                })
                self.assertEqual(response.status_code, 200)
                search.assert_called_once_with(source, "", mode, Page(1, 1), 1,
                                               depth=2, has_children=False)
                roots.assert_not_called()
                self.assertNotContains(response, "reference/catalog.js")
                self.assertContains(response, "لم نعثر على عناوين تطابق البحث")
                pager = [parse_qs(urlsplit(href).query) for href in Links(response.content.decode()).hrefs
                         if "offset=" in href]
                self.assertEqual(len(pager), 2)
                for params in pager:
                    self.assertEqual(params["depth"], ["2"])
                    self.assertEqual(params["has_children"], ["false"])
                    self.assertEqual(params["root"], ["1"])
                    self.assertEqual(params["mode"], [mode])

    def test_ambiguous_filter_only_ssr_fails_closed(self):
        inventory = services.CatalogPage([{}, {}], 2, 100, 0, None)
        for query in ("depth=2", "has_children=false", "root=1"):
            with patch.object(services, "list_books", return_value=inventory):
                self.assertEqual(self.client.get("/fiqh?" + query).status_code, 400)

    def test_api_negative_parameters_are_json_and_redacted(self):
        for query in ("unknown=1", "q=a&q=a", "offset=20001", "limit=0", "limit=101",
                      "root=0", "root=9223372036854775808", "depth=6", "has_children=False",
                      "&".join("q=x" for _ in range(17)), "q=" + "a" * 4097):
            with self.subTest(query=query[:80]):
                response = self.client.get("/api/v1/fiqh/search?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_query")
                self.assertNotIn(b"Traceback", response.content)
        # Exercise the guard itself too, with the framework's field limit.
        with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=16):
            response = views.api_search(RequestFactory().get(
                "/api/v1/fiqh/search?" + "&".join("q=x" for _ in range(17))))
            self.assertEqual(response.status_code, 400)
            self.assertIn("application/json", response["Content-Type"])

    def test_excessive_htmx_branch_parameters_return_controlled_400(self):
        response = self.client.get("/fiqh/nodes/1/children?" + "&".join("q=x" for _ in range(17)),
                                   HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"Traceback", response.content)

    def test_search_detail_and_return_preserve_exact_query_filter_page_state(self):
        source, row = edition(), heading(22, 1, 2)
        inventory = services.CatalogPage([services.edition_data(source)], 1, 100, 0, None)
        results = services.CatalogPage([services.heading_data(row)], 42, 20, 20, 40)
        params = {"edition": 7, "basic": "1", "q": "  عِنْوان & بحث  ", "mode": "exact",
                  "root": 1, "depth": 2, "has_children": "false", "limit": 20, "offset": 20}
        with (patch.object(services, "list_books", return_value=inventory),
              patch.object(services, "resolve_edition", return_value=source),
              patch.object(services, "search", return_value=results) as search):
            listing = self.client.get("/fiqh", params)
            detail_url = next(href for href in Links(listing.content.decode()).hrefs
                              if urlsplit(href).path == "/fiqh/nodes/22")
            detail_params = parse_qs(urlsplit(detail_url).query)
            self.assertEqual(detail_params.get("q"), [params["q"]])
            self.assertEqual(detail_params.get("search_offset"), ["20"])
            with (patch.object(services, "node", return_value=row),
                  patch.object(services, "heading_path", return_value=[services.heading_data(heading()), services.heading_data(row)]),
                  patch.object(services, "child_page", return_value=services.CatalogPage([], 0, 20, 0, None))):
                detail = self.client.get(detail_url)
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, "العودة إلى نتائج البحث")
            self.assertContains(detail, "لا توجد عناوين فرعية في هذه القائمة")
            ancestor_url = next(href for href in Links(detail.content.decode()).hrefs
                                if urlsplit(href).path == "/fiqh/nodes/1")
            self.assertEqual(parse_qs(urlsplit(ancestor_url).query).get("search_offset"), ["20"])
            back_url = next(href for href in Links(detail.content.decode()).hrefs
                            if urlsplit(href).path == "/fiqh" and "offset=20" in href)
            self.assertEqual(parse_qs(urlsplit(back_url).query), {k: [str(v)] for k, v in params.items()})
            returned = self.client.get(back_url)
            self.assertContains(returned, escape(params["q"]))
            search.assert_called_with(source, params["q"], "exact", Page(20, 20), 1,
                                      depth=2, has_children=False)

    def test_explicit_empty_search_is_distinct_from_default_root_browsing(self):
        source = edition()
        inventory = services.CatalogPage([services.edition_data(source)], 1, 100, 0, None)
        empty = services.CatalogPage([], 0, 30, 0, None)
        with (patch.object(services, "list_books", return_value=inventory),
              patch.object(services, "resolve_edition", return_value=source),
              patch.object(services, "search", return_value=empty) as search,
              patch.object(services, "roots", return_value=empty) as roots):
            response = self.client.get("/fiqh?q=")
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with(source, "", "normalized", Page(), None,
                                           depth=None, has_children=None)
            roots.assert_not_called()
            self.assertContains(response, "لم نعثر على عناوين تطابق البحث")

    def test_ssr_unavailable_has_native_retry_for_the_same_bookmark(self):
        from django.db import OperationalError
        path = "/fiqh?edition=7&q=%20%D8%B9%D9%86%D9%88%D8%A7%D9%86%20&depth=2&offset=20"
        with patch.object(services, "list_books", side_effect=OperationalError("private-db-detail")):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private-db-detail", status_code=503)
        self.assertContains(response, "إعادة المحاولة", status_code=503)
        self.assertIn(path, Links(response.content.decode()).hrefs)
