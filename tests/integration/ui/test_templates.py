"""A1 SSR template checks without database writes; synthetic context is test-only."""
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class CatalogTemplateTests(SimpleTestCase):
    def context(self, **changes):
        node = {
            "id": 29, "title": '<img src=x onerror="alert(1)"> عنوان عربي',
            "part": "المقدمة", "page": 4, "page_id": 7654321,
            "source_id": "INTERNAL-SOURCE-KEY", "children_count": 0,
        }
        context = {
            "books": [{"id": 7}],
            "edition": {
                "id": 7, "title": "طبعة اختبار", "publisher": "ناشر اختبار",
                "work": {"title_original": "مرجع اختبار", "madhhab": "اختبار",
                         "source_namespace": "internal", "source_book_id": "test-622"},
            },
            "node": node, "ancestors": [node], "query": "", "mode": "normalized",
            "basic": True, "previous_offset": None,
            "results": {"items": [node], "total": 1, "limit": 20, "next_offset": None},
            "pagination_url": "/fiqh",
        }
        return {**context, **changes}

    def test_ssr_escapes_original_title_and_keeps_publication_citation(self):
        html = render_to_string("reference/catalog.html", self.context())
        self.assertIn("&lt;img", html)
        self.assertNotIn('<img src=x', html)
        self.assertIn("طبعة اختبار", html)
        self.assertIn("ناشر اختبار", html)
        self.assertIn("المقدمة", html)
        self.assertIn("الصفحة المطبوعة: 4", html)
        self.assertIn('aria-current="page"', html)
        self.assertIn("/fiqh/nodes/29?edition=7", html)
        for internal in ["INTERNAL-SOURCE-KEY", "7654321", "test-622", 'name="edition" required', 'id="edition"', "اختر الطبعة"]:
            self.assertNotIn(internal, html)

    def test_ssr_pagination_preserves_query_and_basic_navigation(self):
        context = self.context(node=None, ancestors=[], query="صلاة & بحث", previous_offset=0,
                               results={"items": [], "total": 21, "limit": 20, "next_offset": 20})
        html = render_to_string("reference/catalog.html", context)
        self.assertIn("offset=20", html)
        self.assertIn("basic=1", html)
        self.assertIn("%26", html)
        self.assertIn("لم نعثر على عناوين تطابق البحث", html)
        self.assertNotIn("reference/catalog.js", html)

    def test_interactive_template_has_no_public_edition_control(self):
        html = render_to_string("reference/interactive.html", self.context())
        self.assertNotIn('name="edition"', html)
        self.assertNotIn("عرض الطبعة", html)
        self.assertIn('role="tree"', html)
        self.assertIn('aria-describedby="tree-help"', html)
        self.assertIn('id="basic-link"', html)
        self.assertIn('aria-label="صفحات فروع المسار"', html)

    def test_ambiguous_and_empty_catalogs_have_no_edition_chooser(self):
        for books in [[], [{"id": 7}, {"id": 8}]]:
            html = render_to_string("reference/catalog.html", self.context(edition=None, books=books, node=None))
            self.assertNotIn("<select", html)
            self.assertNotIn("اختر الطبعة", html)
            self.assertIn("الفهرس", html)
