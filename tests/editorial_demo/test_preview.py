import os
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import resolve

from apps.editorial_demo.fixtures import ROWS


class PreviewTests(SimpleTestCase):
    # SimpleTestCase prohibits every database connection/query by default.
    url = "/dev/editorial-preview"

    def get(self, path=None, **kwargs):
        return self.client.get(path or self.url, HTTP_HOST="localhost", **kwargs)

    def test_route_and_rtl(self):
        self.assertEqual(resolve(self.url).url_name, "editorial_demo")
        self.assertContains(self.get(), '<html lang="ar" dir="rtl">')

    def test_head(self):
        response = self.client.head(self.url, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_navigation_detail(self):
        response = self.get()
        self.assertContains(response, "/dev/editorial-preview/SYN-001?")
        self.assertContains(self.get(self.url + "/SYN-001"), ROWS[0].question)

    def test_status_filter(self):
        response = self.get(self.url + "?status=needs_revision")
        self.assertContains(response, "SYN-003")
        self.assertNotContains(response, "SYN-001")

    def test_search_combined(self):
        response = self.get(self.url + "?q=الصلاة&status=draft_preparation")
        self.assertContains(response, "SYN-002")
        self.assertNotContains(response, "SYN-004")

    def test_empty(self):
        self.assertContains(self.get(self.url + "?q=nomatch"), "لا توجد أمثلة مطابقة")

    def test_invalid_ids(self):
        for ident in ("missing", "0", "SYN-999", "SYN-001/extra"):
            self.assertEqual(self.get(self.url + "/" + ident).status_code, 404)

    def test_bounds_and_invalid_queries(self):
        for query in (
            {"q": "x" * 81},
            {"status": "published"},
            {"upload": "x"},
            {"q": "\x00"},
            {"q": ["one", "two"]},
        ):
            self.assertEqual(self.get(data=query).status_code, 400)
        self.assertEqual(self.get(data={"q": "x" * 80}).status_code, 200)

    def test_unsafe_methods(self):
        for path in (self.url, self.url + "/SYN-001", self.url + "/style.css"):
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                response = getattr(self.client, method)(path, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Allow"], "GET, HEAD")

    def test_escaping(self):
        payload = '<script>alert("x")</script>'
        self.assertNotContains(self.get(data={"q": payload}), payload)
        self.assertContains(self.get(data={"q": payload}), "&lt;script&gt;")
        with patch("apps.editorial_demo.views.ROWS", (replace(ROWS[0], question=payload),)):
            response = self.get(self.url + "/SYN-001")
            self.assertNotContains(response, payload)
            self.assertContains(response, "&lt;script&gt;")

    def test_semantics(self):
        response = self.get(self.url + "/SYN-001")
        for text in (
            "بيانات وهمية بالكامل",
            "غير منشورة",
            "missing_manual_references",
            "لا توجد إجابة",
            "المراجع غير المحسومة",
            "Gate B NOT_PASSED",
            "fatwa.prepared-intake.v1",
            "خطوات المراجعة البشرية",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, '<a href="https://example.invalid')
        self.assertNotContains(response, "<textarea")

    def test_keyboard_landmarks(self):
        response = self.get()
        for text in (
            'href="#main-content"',
            '<main id="main-content" tabindex="-1">',
            '<label for="q">',
            '<label for="status">',
            "<nav aria-label=",
            'type="submit"',
            'name="viewport"',
        ):
            self.assertContains(response, text)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_host_and_peer_restrictions(self):
        for host in ("example.com", "localhost.example.com", "127.0.0.2"):
            self.assertEqual(self.client.get(self.url, HTTP_HOST=host).status_code, 404)
        self.assertEqual(self.get(REMOTE_ADDR="192.0.2.1").status_code, 404)
        self.assertEqual(self.get(REMOTE_ADDR="").status_code, 404)
        self.assertEqual(
            self.client.get(self.url, HTTP_HOST="[::1]:8000", REMOTE_ADDR="::1").status_code, 200
        )

    def test_production_disabled(self):
        with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
            self.assertEqual(self.get().status_code, 404)
            self.assertEqual(self.get(self.url + "/style.css").status_code, 404)

    def test_stylesheet_and_headers(self):
        response = self.get(self.url + "/style.css")
        self.assertContains(response, ":focus-visible")
        self.assertEqual(response["Content-Type"], "text/css; charset=utf-8")
        self.assertEqual(self.get()["Cache-Control"], "no-store")

    def test_pages_without_database(self):
        for path in (self.url, self.url + "/SYN-002", self.url + "/style.css"):
            self.assertEqual(self.get(path).status_code, 200)
