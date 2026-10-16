"""A5 isolated Django tests. Synthetic data; SimpleTestCase forbids database access.

Not live HTTP or PostgreSQL acceptance. No fixtures/imports/migrations or DB writes.
Run: python -B manage.py test tests/security --settings=config.settings.test
"""

from html import escape
from html.parser import HTMLParser
from types import SimpleNamespace

from django.db import DatabaseError
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase

from apps.reference import services, views
from apps.reference.query import InvalidQuery, Page


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class A5IsolatedPublicSecurityTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        self.factory = RequestFactory()
        self.title = 'عنوان عربي <img src=x onerror=alert(622)> & "نص"'
        self.marker = "A5_PRIVATE_CANARY_ONLY_IN_MEMORY"
        self.work = SimpleNamespace(
            source_namespace="synthetic", source_book_id="a5-only",
            title_original="مرجع اصطناعي", madhhab="اختبار",
        )
        self.edition = SimpleNamespace(
            pk=1, edition_key="a5-synthetic", title="طبعة اصطناعية", publisher="ناشر اختبار",
            heading_count=1, root_count=1, max_depth=1,
            source_archive_sha256="a" * 64, source_input_sha256="b" * 64,
            work=self.work, input_name=self.marker, ingest_checksum=self.marker,
            private_case=self.marker,
        )
        self.record = SimpleNamespace(
            pk=999999, source_row_id=25, source_id="a5-25", parent_source_row_id=None,
            title_original=self.title, depth=1, position=1, source_order=1,
            children_count=1, source_part="المقدمة", source_page_number=7,
            source_page_id=925, source_entry_number=None, fatwa_text=self.marker,
            requester=self.marker, title_normalized=self.marker,
        )

    def test_arabic_source_title_is_escaped_in_actual_ssr_templates(self):
        row = services.heading_data(self.record)
        edition = services.edition_data(self.edition)
        context = {
            "books": [edition], "edition": edition, "query": self.title, "mode": "exact",
            "basic": True, "page": Page(), "node": row, "ancestors": [row],
            "results": services.CatalogPage([row], 1, 30, 0, None),
            "previous_offset": None, "pagination_url": "/fiqh",
        }
        html = render_to_string(
            "reference/catalog.html", context, request=self.factory.get("/fiqh")
        )
        self.assertIn(escape(self.title), html)
        self.assertNotIn(self.title, html)
        self.assertNotIn(self.marker, html)
        parsed = Tags()
        parsed.feed(html)
        self.assertFalse(any(tag == "img" for tag, _ in parsed.tags))
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.tags for key in attrs))
        self.assertTrue(any(tag == "html" and attrs.get("lang") == "ar"
                            and attrs.get("dir") == "rtl" for tag, attrs in parsed.tags))

    def test_heading_projection_preserves_source_id_and_never_exposes_database_pk_or_case(self):
        data = services.heading_data(self.record)
        self.assertEqual(data["id"], 25)
        self.assertEqual(data["source_id"], "a5-25")
        self.assertNotIn(self.record.pk, data.values())
        self.assertNotIn(self.marker, str(data))
        self.assertNotIn("fatwa_text", data)
        self.assertNotIn("requester", data)
        self.assertEqual(data["title"], self.title)

    def test_edition_projection_preserves_hashes_without_internal_filename_or_case(self):
        data = services.edition_data(self.edition)
        self.assertEqual(data["edition_key"], "a5-synthetic")
        self.assertEqual(data["source_archive_sha256"], "a" * 64)
        self.assertEqual(data["source_input_sha256"], "b" * 64)
        self.assertNotIn(self.marker, str(data))
        self.assertNotIn("input_name", data)
        self.assertNotIn("private_case", data)

    def test_api_errors_are_generic_json_even_when_internal_exception_has_private_text(self):
        for error, status, code in [
            (InvalidQuery(self.marker), 400, "invalid_query"),
            (services.HeadingNotFound(self.marker), 404, "not_found"),
            (DatabaseError(self.marker), 503, "catalog_unavailable"),
            (services.CatalogUnavailable(self.marker), 503, "catalog_unavailable"),
        ]:
            with self.subTest(status=status, exception=type(error).__name__):
                def fail(request):
                    raise error
                response = views.api_guard(fail)(self.factory.get("/api/v1/fiqh/roots"))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response["Content-Type"], "application/json")
                self.assertIn(code.encode(), response.content)
                self.assertNotIn(self.marker.encode(), response.content)

    def test_private_get_and_csrf_style_post_require_no_database_and_are_denied(self):
        client = Client(enforce_csrf_checks=True)
        for route in ["/admin/", "/accounts/login/", "/api/v1/private/cases", "/api/v1/ai/answer"]:
            with self.subTest(route=route):
                self.assertEqual(client.get(route).status_code, 404)
                response = client.post(route, HTTP_ORIGIN="https://a5.invalid")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Allow"], "GET, HEAD")
                self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_unsafe_public_methods_never_enter_the_service_or_database(self):
        client = Client(enforce_csrf_checks=True)
        for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
            for route in ["/fiqh", "/api/v1/fiqh/books", "/api/v1/fiqh/nodes/25"]:
                with self.subTest(method=method, route=route):
                    response = client.generic(method, route)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response.json(), {"error": "method_not_allowed"})
                    self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_unknown_and_duplicate_parameters_are_rejected_before_catalog_access(self):
        client = Client()
        for query in ["limit=1&limit=2", "requester=x", "callback=alert", "input_name=x"]:
            with self.subTest(query=query):
                response = client.get("/api/v1/fiqh/books?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {
                    "kind": "SOURCE_BOOK_TOC_NOT_FATWAS", "error": "invalid_query"
                })
