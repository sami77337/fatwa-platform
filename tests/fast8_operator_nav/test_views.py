import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_workbench.services import WorkbenchDataError
from apps.reference_links.resolution import CatalogReadError


class LinkParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


@override_settings(ROOT_URLCONF="tests.fast8_operator_nav.urls")
class NavigationTests(SimpleTestCase):
    def get(self, path="/operator", **kwargs):
        return self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **kwargs)

    def test_catalog_has_actual_case_links_and_identity(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for row in build_queue_catalog().rows:
            self.assertContains(response, f"/operator/{row.case.key}")
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, "NOT_CONNECTED")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_sparse_revision_identity_and_destination_scope(self):
        response = self.get("/operator/history?revision=4&q=history")
        self.assertContains(response, "/dev/editorial-workbench/history?revision=4#snapshot")
        self.assertContains(response, '/dev/research-bridge/history"')
        self.assertContains(response, '/dev/editorial-export"')
        self.assertNotContains(response, "/dev/editorial-export?")
        self.assertContains(response, "المجموعة كاملة")
        self.assertContains(response, 'data-revision="4"')
        self.assertContains(response, "revision=7")
        self.assertNotContains(response, "revision=3")
        row = next(row for row in build_queue_catalog().rows if row.case.key == "history")
        self.assertContains(response, row.source_sha256)

    def test_search_reuses_real_hits_with_revision(self):
        from apps.editorial_search.services import search_catalog

        result = search_catalog(build_queue_catalog(), q="اصطناعي")
        response = self.get("/operator", data={"q": "اصطناعي"})
        self.assertContains(response, f'data-total="{result.total}"')
        for hit in result.hits:
            if hit.case_key:
                self.assertContains(response, f"/operator/{hit.case_key}?")
                if hit.revision:
                    self.assertContains(response, f"revision={hit.revision}")

    def test_bad_queries_and_unknown_identities(self):
        for path, status in (
            ("/operator?revision=1", 400),
            ("/operator?q=a&q=b", 400),
            ("/operator?q=" + "x" * 81, 400),
            ("/operator?q=%00", 400),
            ("/operator?next=https://example.org", 400),
            ("/operator?page=01", 400),
            ("/operator?page=20", 400),
            ("/operator/history?revision=04", 400),
            ("/operator/history?revision=3", 404),
            ("/operator/missing", 404),
            ("/operator/style.css?q=a", 400),
        ):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_no_draft_does_not_infer_revision(self):
        row = next(row for row in build_queue_catalog().rows if not row.history)
        self.assertContains(self.get(f"/operator/{row.case.key}"), "لا توجد مراجعات")
        self.assertEqual(self.get(f"/operator/{row.case.key}?revision=1").status_code, 400)

    @override_settings(ROOT_URLCONF="tests.fast8_operator_nav.isolated_urls")
    def test_unmounted_services_have_no_invented_hrefs(self):
        response = self.get("/operator/history?revision=4")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NOT_CONNECTED", count=6)
        self.assertNotContains(response, 'href="/dev/')

    def test_guards_run_before_loading_catalog(self):
        with patch("apps.fast8_operator_nav.views.build_queue_catalog") as build:
            for path in ("/operator", "/operator/history", "/operator/style.css"):
                for host, peer in (("localhost", "192.0.2.1"), ("testserver", "127.0.0.1")):
                    response = self.client.get(path, HTTP_HOST=host, REMOTE_ADDR=peer)
                    self.assertEqual(response.status_code, 404)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(path).status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(path).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(path).status_code, 404)
            build.assert_not_called()

    def test_methods_and_head(self):
        for path in ("/operator", "/operator/history", "/operator/style.css"):
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                response = getattr(self.client, method)(path, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 405)
            response = self.client.head(path, HTTP_HOST="localhost", REMOTE_ADDR="::1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")

    def test_source_failure_is_explicit(self):
        with patch(
            "apps.fast8_operator_nav.views.build_queue_catalog", side_effect=WorkbenchDataError
        ):
            response = self.get()
        self.assertContains(response, "NOT_SUPPLIED", status_code=503)

    def test_every_case_service_link_is_executable(self):
        with patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            side_effect=CatalogReadError("explicit unavailable catalog"),
        ):
            for row in build_queue_catalog().rows:
                response = self.get(f"/operator/{row.case.key}")
                for link in LinkParser(response.content.decode()).links:
                    if link.startswith("/dev/"):
                        with self.subTest(case=row.case.key, link=link):
                            target = self.get(link)
                            self.assertEqual(target.status_code, 200)
                            if "#" in link:
                                self.assertContains(target, f'id="{link.split("#")[1]}"')

    def test_escaping_and_exact_crlf_rendering(self):
        catalog = build_queue_catalog()
        original = catalog.rows[0]
        fabricated = '\nسُؤالٌ اصطناعي\r\n<script>alert("synthetic")</script>'
        row = replace(original, case=replace(original.case, question=fabricated))
        with patch(
            "apps.fast8_operator_nav.views.build_queue_catalog",
            return_value=replace(catalog, rows=(row, *catalog.rows[1:])),
        ):
            response = self.get(f"/operator/{row.case.key}")
        self.assertContains(response, "<code>\nسُؤالٌ اصطناعي&#13;\n&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertEqual(original.case.question, build_queue_catalog().rows[0].case.question)

    def test_empty_results_and_pagination_preserve_search(self):
        response = self.get("/operator?q=synthetic-no-match-38919")
        self.assertContains(response, "لا توجد نتائج مطابقة")
        response = self.get("/operator", data={"q": "اصطناعي", "page": 2})
        self.assertEqual(response.status_code, 200)
        links = LinkParser(response.content.decode()).links
        detail = next(link for link in links if link.startswith("/operator/"))
        page = self.get(detail)
        self.assertContains(page, "page=2")

    def test_direct_views_reject_writes_without_middleware(self):
        from django.test import RequestFactory

        from apps.fast8_operator_nav.views import navigation, stylesheet

        request = RequestFactory().post("/operator", HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
        with patch("apps.fast8_operator_nav.views.build_queue_catalog") as build:
            for view in (navigation, stylesheet):
                self.assertEqual(view(request).status_code, 405)
            build.assert_not_called()
