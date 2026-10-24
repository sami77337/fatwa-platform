"""Native Arabic navigation regressions using synthetic source projections only."""

from contextlib import contextmanager
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from apps.reference import services
from tests.integration.api.test_catalog import cursor_rows, edition, heading


class NavigationHTML(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.tags = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def links(self, path):
        return [
            attrs["href"]
            for tag, attrs in self.tags
            if tag == "a" and urlsplit(attrs.get("href", "")).path == path
        ]


class NativeNavigationTests(SimpleTestCase):
    @contextmanager
    def catalog(self, *, items=(), total=None, offset=0, limit=2, path=None):
        source = edition()
        selected = heading(33, 22, 3)
        ancestors = path or [heading(11), heading(22, 11, 2), selected]
        result = services.CatalogPage(
            [services.heading_data(row) for row in items],
            len(items) if total is None else total,
            limit,
            offset,
            None,
        )
        with (
            patch.object(
                services,
                "list_books",
                return_value=services.CatalogPage([services.edition_data(source)], 1, 100, 0, None),
            ),
            patch.object(services, "resolve_edition", return_value=source),
            patch.object(services, "node", return_value=selected),
            patch.object(
                services,
                "heading_path",
                return_value=[services.heading_data(row) for row in ancestors],
            ),
            patch.object(services, "child_page", return_value=result),
            patch.object(services, "roots", return_value=result),
            patch.object(services, "search", return_value=result),
        ):
            yield

    def test_breadcrumbs_reveal_the_next_child_and_preserve_search_state(self):
        with self.catalog():
            response = self.client.get(
                "/fiqh/nodes/33",
                {
                    "edition": 7,
                    "basic": 1,
                    "limit": 2,
                    "q": "  أَبْوَاب & بحث  ",
                    "mode": "exact",
                    "depth": 3,
                    "has_children": "false",
                    "search_offset": 8,
                },
            )
        self.assertEqual(response.status_code, 200)
        html = NavigationHTML(response)
        for parent, child in ((11, 22), (22, 33)):
            link = html.links(f"/fiqh/nodes/{parent}")[0]
            params = parse_qs(urlsplit(link).query)
            self.assertEqual(params.get("anchor"), [str(child)])
            self.assertEqual(params.get("search_offset"), ["8"])
            self.assertEqual(params.get("limit"), ["2"])
            self.assertEqual(params.get("q"), ["  أَبْوَاب & بحث  "])
            self.assertEqual(urlsplit(link).fragment, f"heading-row-{child}")
        root_link = next(link for link in html.links("/fiqh") if "anchor=" in link)
        self.assertEqual(parse_qs(urlsplit(root_link).query).get("anchor"), ["11"])

    def test_nonsearch_detail_links_keep_page_size(self):
        with self.catalog(items=[heading(22, 11, 2)]):
            response = self.client.get("/fiqh?edition=7&basic=1&limit=2")
        link = NavigationHTML(response).links("/fiqh/nodes/22")[0]
        self.assertEqual(parse_qs(urlsplit(link).query).get("limit"), ["2"])

    def test_anchor_selects_native_view_and_marks_target(self):
        row = heading(22, 11, 2)
        with self.catalog(items=[row]):
            response = self.client.get("/fiqh/nodes/11?edition=7&anchor=22&limit=2")
        self.assertContains(response, 'id="heading-row-22"')
        html = NavigationHTML(response)
        selected = [attrs for tag, attrs in html.tags if attrs.get("aria-current") == "location"]
        self.assertTrue(selected)
        self.assertNotContains(response, 'src="/assets/reference/catalog.js"')

    def test_empty_out_of_range_page_offers_same_filtered_first_page(self):
        with self.catalog(total=3, offset=10):
            response = self.client.get(
                "/fiqh",
                {
                    "edition": 7,
                    "basic": 1,
                    "q": "أبواب",
                    "mode": "literal",
                    "depth": 2,
                    "has_children": "false",
                    "limit": 2,
                    "offset": 10,
                },
            )
        self.assertContains(response, "لا توجد عناوين في هذه الصفحة")
        recovery = next(
            link
            for link in NavigationHTML(response).links("/fiqh")
            if parse_qs(urlsplit(link).query).get("offset") == ["0"]
        )
        params = parse_qs(urlsplit(recovery).query)
        self.assertEqual(params.get("q"), ["أبواب"])
        self.assertEqual(params.get("depth"), ["2"])
        self.assertEqual(params.get("has_children"), ["false"])

    def test_detail_offers_filter_only_search_inside_its_root(self):
        with self.catalog():
            response = self.client.get("/fiqh/nodes/33?edition=7&basic=1&limit=2")
        self.assertContains(response, "البحث داخل هذا الجذر")
        scoped = next(
            link
            for link in NavigationHTML(response).links("/fiqh")
            if parse_qs(urlsplit(link).query).get("root") == ["11"]
        )
        self.assertEqual(parse_qs(urlsplit(scoped).query).get("limit"), ["2"])

    def test_missing_heading_has_arabic_recovery_link_for_validated_edition(self):
        with self.catalog(), patch.object(services, "node", side_effect=services.HeadingNotFound):
            response = self.client.get("/fiqh/nodes/999?edition=7&basic=1")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "العنوان المطلوب غير موجود", status_code=404)
        self.assertIn("/fiqh?edition=7&basic=1", NavigationHTML(response).links("/fiqh"))

    def test_missing_edition_recovery_drops_the_invalid_edition(self):
        inventory = services.CatalogPage([services.edition_data(edition())], 1, 100, 0, None)
        with patch.object(services, "list_books", return_value=inventory), cursor_rows([]):
            response = self.client.get("/fiqh?edition=999&basic=1")
        self.assertEqual(response.status_code, 404)
        self.assertIn("/fiqh?basic=1", NavigationHTML(response).links("/fiqh"))
        self.assertNotIn("/fiqh?edition=999&basic=1", NavigationHTML(response).links("/fiqh"))

    def test_invalid_query_explains_recovery_and_does_not_echo_untrusted_text(self):
        response = self.client.get("/fiqh?mode=unknown&q=private-sentinel")
        self.assertContains(response, "تحقق من معلمات البحث", status_code=400)
        self.assertNotContains(response, "private-sentinel", status_code=400)

    def test_ambiguous_catalog_offers_each_edition_as_a_native_link(self):
        inventory = services.CatalogPage(
            [
                services.edition_data(edition(7)),
                services.edition_data(edition(8)),
            ],
            2,
            100,
            0,
            None,
        )
        with patch.object(services, "list_books", return_value=inventory):
            response = self.client.get("/fiqh")
        self.assertContains(response, "اختر الطبعة")
        choices = NavigationHTML(response).links("/fiqh")
        for ident in (7, 8):
            self.assertIn(f"/fiqh?edition={ident}&basic=1", choices)

    def test_removing_root_scope_keeps_other_search_filters_and_resets_page(self):
        with self.catalog():
            response = self.client.get(
                "/fiqh?edition=7&q=%D8%A3%D8%A8%D9%88%D8%A7%D8%A8&root=11&depth=2&has_children=false&offset=8&limit=2"
            )
        self.assertContains(response, "البحث في جميع الجذور")
        link = next(
            attrs["href"]
            for tag, attrs in NavigationHTML(response).tags
            if attrs.get("id") == "clear-root-scope"
        )
        self.assertEqual(
            parse_qs(urlsplit(link).query),
            {
                "edition": ["7"],
                "basic": ["1"],
                "limit": ["2"],
                "q": ["أبواب"],
                "mode": ["normalized"],
                "depth": ["2"],
                "has_children": ["false"],
            },
        )
