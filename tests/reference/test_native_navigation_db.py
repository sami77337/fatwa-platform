"""Real PostgreSQL navigation over native-navigation-v1 synthetic headings only."""

from dataclasses import replace
from html import escape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from apps.reference.records import CatalogSpec, HeadingRecord


class NavigationLinks(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.current = None
        self.feed(content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {**dict(attrs), "text": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None

    def href(self, text):
        return next(link["href"] for link in self.links if link["text"] == text)


class NativeNavigationDatabaseTests(TestCase):
    fixture_identity = "native-navigation-v1"
    exact_title = "عُنْوَانٌ آمِنٌ 100%_& <script>اختبار</script>"

    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Real PostgreSQL 17 or 18 required")
        definitions = (
            (10, None, 1, 10, "جذر أول"),
            (20, None, 1, 100, "جذر ثان"),
            (30, None, 1, 500, "جذر ثالث"),
            (31, 30, 2, 10, cls.exact_title),
            (32, 30, 2, 70, cls.exact_title),
            (33, 30, 2, 900, cls.exact_title),
            (37, 33, 3, 10, "فرع أول"),
            (38, 33, 3, 20, "فرع ثان"),
            (34, 33, 3, 700, "فرع ثالث"),
            (35, 34, 4, 900, "مسار رابع"),
            (36, 35, 5, 999, "عُنْوَانُ النهاية & <اختبار>"),
        )
        cls.rows = tuple(
            HeadingRecord(
                source_id=f"native-navigation-v1-{ident}",
                source_row_id=ident,
                parent_source_row_id=parent,
                source_order=order,
                position=position,
                depth=depth,
                source_page_id=1000 + ident,
                source_part="جُزْءٌ اصطناعي & <أصل>",
                source_page_number=ident,
                title_original=title,
            )
            for order, (ident, parent, depth, position, title) in enumerate(definitions, 1)
        )
        cls.spec = CatalogSpec(
            source_namespace="synthetic",
            source_book_id=cls.fixture_identity,
            work_title="مرجع تنقل اصطناعي",
            madhhab="اختبار",
            edition_key=cls.fixture_identity,
            edition_title="طبعة اصطناعية",
            publisher="ناشر اصطناعي",
            source_archive_sha256="d" * 64,
            source_input_sha256="e" * 64,
            input_name="native-navigation-v1.jsonl",
            expected_rows=11,
            expected_roots=3,
            expected_max_depth=5,
        )
        preview = ingest_catalog(cls.spec, cls.rows)
        cls.edition_id = ingest_catalog(
            cls.spec, cls.rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        other_spec = replace(
            cls.spec,
            edition_key="native-navigation-other-edition-v1",
            input_name="native-navigation-other-edition-v1.jsonl",
            expected_rows=1,
            expected_roots=1,
            expected_max_depth=1,
        )
        other_rows = (
            replace(
                cls.rows[0],
                source_id="other-edition-root-999",
                source_row_id=999,
            ),
        )
        other_preview = ingest_catalog(other_spec, other_rows)
        ingest_catalog(
            other_spec, other_rows, dry_run=False, expected_checksum=other_preview.checksum
        )

    def native_get(self, path, params=None, budget=11):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, params)
        self.assertLessEqual(len(queries), budget, [query["sql"] for query in queries])
        self.assertTrue(all(query["sql"].lstrip().startswith("SELECT") for query in queries))
        return response, len(queries)

    def test_deep_breadcrumbs_reveal_the_actual_child_and_root_pages(self):
        detail, count = self.native_get(
            "/fiqh/nodes/36", {"edition": self.edition_id, "basic": 1, "limit": 2}
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(count, 9)
        links = NavigationLinks(detail.content)
        self.assertContains(detail, escape(self.rows[-1].title_original))
        self.assertNotContains(detail, "<اختبار>")
        expected = ((30, 33, 2), (33, 34, 2), (34, 35, 0), (35, 36, 0))
        for parent, child, offset in expected:
            with self.subTest(parent=parent):
                url = next(
                    link["href"]
                    for link in links.links
                    if urlsplit(link["href"]).path == f"/fiqh/nodes/{parent}"
                )
                params = parse_qs(urlsplit(url).query)
                self.assertEqual(params["edition"], [str(self.edition_id)])
                self.assertEqual(params["anchor"], [str(child)])
                self.assertEqual(params["limit"], ["2"])
                self.assertEqual(urlsplit(url).fragment, f"heading-row-{child}")
                page, _ = self.native_get(url)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["results"].offset, offset)
                self.assertIn(child, [item["id"] for item in page.context["results"].items])
                self.assertContains(page, f'id="heading-row-{child}"')
                self.assertContains(page, 'aria-current="location"')
        roots, root_count = self.native_get(links.href("جذور الفهرس"), budget=7)
        self.assertEqual(root_count, 7)
        self.assertEqual(roots.context["results"].offset, 2)
        self.assertEqual([item["id"] for item in roots.context["results"].items], [30])
        self.assertContains(roots, 'aria-current="location"')

    def test_arabic_search_modes_and_independent_search_child_offsets(self):
        for mode, query in (
            ("normalized", "عنوان امن"),
            ("literal", "100%_&"),
            ("exact", self.exact_title),
        ):
            with self.subTest(mode=mode):
                params = {
                    "edition": self.edition_id,
                    "basic": 1,
                    "q": query,
                    "mode": mode,
                    "root": 30,
                    "depth": 2,
                    "limit": 2,
                    "offset": 2,
                }
                results, _ = self.native_get("/fiqh", params)
                self.assertEqual(results.status_code, 200)
                self.assertEqual(results.context["results"].total, 3)
                self.assertEqual([row["id"] for row in results.context["results"].items], [33])
                item = results.context["results"].items[0]
                self.assertEqual(item["source_id"], "native-navigation-v1-33")
                self.assertEqual(item["title"], self.exact_title)
                self.assertContains(results, escape(self.exact_title))
                self.assertNotContains(results, "<script>اختبار</script>")
                link = next(
                    link["href"]
                    for link in NavigationLinks(results.content).links
                    if urlsplit(link["href"]).path == "/fiqh/nodes/33"
                )
                detail, _ = self.native_get(link)
                self.assertEqual(detail.context["results"].offset, 0)
                self.assertEqual(detail.context["search_offset"], 2)
                next_page = NavigationLinks(detail.content).href("التالي")
                children, _ = self.native_get(next_page)
                self.assertEqual(children.context["results"].offset, 2)
                self.assertEqual([item["id"] for item in children.context["results"].items], [34])
                self.assertEqual(children.context["search_offset"], 2)
                returned_url = NavigationLinks(children.content).href("العودة إلى نتائج البحث")
                self.assertEqual(
                    parse_qs(urlsplit(returned_url).query),
                    {key: [str(value)] for key, value in params.items()},
                )
                returned, _ = self.native_get(returned_url)
                self.assertEqual([item["id"] for item in returned.context["results"].items], [33])

    def test_missing_nonroot_and_cross_edition_anchors_offer_safe_recovery(self):
        for anchor in (998, 999, 33):
            with self.subTest(anchor=anchor):
                response, _ = self.native_get(
                    "/fiqh",
                    {
                        "edition": self.edition_id,
                        "basic": 1,
                        "limit": 2,
                        "anchor": anchor,
                    },
                )
                self.assertEqual(response.status_code, 404)
                recovery = NavigationLinks(response.content).href("العودة إلى الفهرس")
                self.assertEqual(
                    parse_qs(urlsplit(recovery).query),
                    {
                        "edition": [str(self.edition_id)],
                        "basic": ["1"],
                    },
                )
                roots, _ = self.native_get(recovery)
                self.assertEqual(roots.status_code, 200)
        invalid, _ = self.native_get(
            "/fiqh",
            {
                "edition": self.edition_id,
                "basic": 1,
                "anchor": 30,
                "offset": 0,
            },
        )
        self.assertEqual(invalid.status_code, 400)

    def test_out_of_range_page_recovery_preserves_search_and_source_unicode(self):
        params = {
            "edition": self.edition_id,
            "basic": 1,
            "q": self.exact_title,
            "mode": "exact",
            "root": 30,
            "depth": 2,
            "has_children": "false",
            "limit": 2,
            "offset": 20000,
        }
        empty, _ = self.native_get("/fiqh", params)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.context["results"].total, 2)
        first_url = NavigationLinks(empty.content).href("العودة إلى الصفحة الأولى")
        self.assertEqual(
            parse_qs(urlsplit(first_url).query),
            {
                **{key: [str(value)] for key, value in params.items()},
                "offset": ["0"],
            },
        )
        first, _ = self.native_get(first_url)
        self.assertEqual([item["id"] for item in first.context["results"].items], [31, 32])
        self.assertEqual(
            list(
                ReferenceHeading.objects.filter(edition_id=self.edition_id)
                .order_by("source_order")
                .values_list("source_id", "title_original", "source_part")
            ),
            [(row.source_id, row.title_original, row.source_part) for row in self.rows],
        )
