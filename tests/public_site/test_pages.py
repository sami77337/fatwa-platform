"""Public SSR tests with mocked catalog summaries; never seed or touch a database.

Fixture identity: a3-public-source-summary-v1, synthetic service output only.
These tests do not establish owner-source or PostgreSQL acceptance.
"""

from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from django.db import OperationalError
from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from apps.public_site import views
from apps.reference import views as reference_views
from apps.reference.query import Page
from apps.reference.services import CatalogPage, CatalogUnavailable


class Elements(HTMLParser):
    def __init__(self, content: bytes) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict]] = []
        self.feed(content.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def find(self, tag: str) -> list[dict]:
        return [attrs for name, attrs in self.elements if name == tag]


# Deliberately synthetic metadata. Internal edition fields must never become controls.
SOURCE = {
    "id": 73,
    "title": "طبعة اختبار داخلية",
    "edition_key": "a3-synthetic-internal-edition",
    "publisher": "ناشر اختبار",
    "heading_count": 987654,
    "source_archive_sha256": "a" * 64,
    "work": {"title_original": "مرجع اصطناعي لاختبار الصفحة العامة"},
}


class PublicPageTests(SimpleTestCase):
    def setUp(self) -> None:
        self.books = self.enterContext(
            patch("apps.public_site.views.list_books", return_value=CatalogPage([], 0, 1, 0, None))
        )

    def one_source(self) -> None:
        self.books.return_value = CatalogPage([SOURCE], 1, 1, 0, None)

    def test_routes_keep_existing_names_and_handlers(self) -> None:
        self.assertEqual(reverse("home"), "/")
        self.assertEqual(reverse("public_help"), "/help")
        self.assertIs(resolve("/").func, views.home)
        self.assertIs(resolve("/help").func, views.help_page)
        for route, name, handler in [
            ("/fiqh", "catalog", reference_views.catalog),
            ("/fiqh/nodes/1", "heading", reference_views.catalog),
            ("/fiqh/nodes/1/children", "branch", reference_views.branch),
            ("/healthz", "health", reference_views.health),
            ("/readyz", "ready", reference_views.ready),
            ("/api/v1/status", "status", reference_views.status),
            ("/api/v1/fiqh/books", "api_books", reference_views.api_books),
            ("/api/v1/fiqh/roots", "api_roots", reference_views.api_roots),
            ("/api/v1/fiqh/search", "api_search", reference_views.api_search),
            ("/api/v1/fiqh/nodes/1", "api_node", reference_views.api_node),
            ("/api/v1/fiqh/nodes/1/children", "api_children", reference_views.api_children),
            ("/assets/reference/style.css", "public_asset", reference_views.public_asset),
        ]:
            with self.subTest(route=route):
                match = resolve(route)
                self.assertEqual(match.url_name, name)
                self.assertIs(match.func, handler)

    def test_empty_source_keeps_home_help_and_catalog_links_available(self) -> None:
        response = self.client.get("/")
        self.assertContains(response, "لم يُحمّل فهرس مرجعي بعد")
        self.assertNotContains(response, "المرجع المتاح")
        self.assertFalse(Elements(response.content).find("form"))
        self.assertContains(response, 'href="/fiqh?basic=1"')
        self.assertContains(response, 'href="/help"')
        self.books.assert_called_once_with(Page(1))
        self.assertEqual(self.client.get("/help").status_code, 200)

    def test_one_source_shows_original_work_title_without_invented_statistics(self) -> None:
        self.one_source()
        response = self.client.get("/")
        self.assertContains(response, SOURCE["work"]["title_original"])
        self.assertNotContains(response, "لم يُحمّل")
        self.assertNotContains(response, str(SOURCE["heading_count"]))
        self.books.assert_called_once_with(Page(1))

    def test_multiple_sources_do_not_silently_choose_a_source_or_offer_a_selector(self) -> None:
        self.books.return_value = CatalogPage([SOURCE], 2, 1, 0, 1)
        response = self.client.get("/")
        self.assertContains(response, "يمكن الوصول إلى المراجع المتاحة من صفحة الفهرس")
        self.assertNotContains(response, SOURCE["work"]["title_original"])
        self.assertFalse(Elements(response.content).find("select"))
        self.assertFalse(Elements(response.content).find("form"))

    def test_help_is_available_without_any_catalog_read(self) -> None:
        self.books.side_effect = AssertionError("Help must not access catalog storage")
        response = self.client.get("/help")
        for text in ["كشاف القناع", "وزارة العدل", "الحنبلي", "الصفحة المطبوعة", "نص الكتاب"]:
            self.assertContains(response, text)
        self.books.assert_not_called()

    def test_source_outage_keeps_public_pages_reachable_and_redacts_details(self) -> None:
        for error in [
            OperationalError("secret-connection-string"),
            CatalogUnavailable("secret-path"),
        ]:
            with self.subTest(error=type(error).__name__):
                self.books.side_effect = error
                response = self.client.get("/")
                self.assertContains(response, "تعذر الوصول إلى الفهرس حاليًا")
                self.assertNotContains(response, "secret-")
                self.assertFalse(Elements(response.content).find("form"))
                self.assertEqual(self.client.get("/help").status_code, 200)

    def test_source_title_is_escaped(self) -> None:
        title = '<script>alert("source")</script>'
        source = {**SOURCE, "work": {"title_original": title}}
        self.books.return_value = CatalogPage([source], 1, 1, 0, None)
        response = self.client.get("/")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, title)
        self.assertFalse(Elements(response.content).find("script"))

    def test_public_navigation_links_resolve_and_identify_current_page(self) -> None:
        for route in ["/", "/help"]:
            with self.subTest(route=route):
                document = Elements(self.client.get(route).content)
                current = [a["href"] for a in document.find("a") if a.get("aria-current") == "page"]
                self.assertEqual(current, [route])
                for anchor in document.find("a"):
                    href = anchor["href"]
                    if not href.startswith("#"):
                        self.assertIn(urlsplit(href).path, {"/", "/help", "/fiqh"})
                        resolve(urlsplit(href).path)
                self.assertTrue(
                    any(n.get("aria-label") == "التنقل الرئيسي" for n in document.find("nav"))
                )

    def test_search_form_submits_to_existing_ssr_search(self) -> None:
        self.one_source()
        document = Elements(self.client.get("/").content)
        (form,) = document.find("form")
        self.assertEqual(form, {"role": "search", "method": "get", "action": "/fiqh"})
        fields = {i["name"]: i for i in document.find("input")}
        self.assertEqual(set(fields), {"q", "basic"})
        self.assertEqual(fields["basic"]["value"], "1")
        self.assertEqual(fields["q"]["maxlength"], "160")
        self.assertIn("required", fields["q"])
        self.assertTrue(
            any(label.get("for") == fields["q"]["id"] for label in document.find("label"))
        )
        query = "عنوان اختبار"
        with (
            patch(
                "apps.reference.views.services.list_books",
                return_value=CatalogPage([], 0, 100, 0, None),
            ),
            patch("apps.reference.views.services.resolve_edition", return_value=None),
            patch(
                "apps.reference.views.services.search", return_value=CatalogPage([], 0, 30, 0, None)
            ) as search,
        ):
            response = self.client.get(form["action"] + "?" + urlencode({"basic": "1", "q": query}))
        self.assertEqual(response.status_code, 200)
        search.assert_called_once_with(None, query, "normalized", Page())
        self.assertNotContains(response, "reference/catalog.js")

    def test_pages_have_rtl_landmarks_skip_link_and_no_client_script(self) -> None:
        self.one_source()
        for route in ["/", "/help"]:
            with self.subTest(route=route):
                response = self.client.get(route)
                document = Elements(response.content)
                self.assertContains(response, 'lang="ar" dir="rtl"')
                self.assertEqual(len(document.find("h1")), 1)
                self.assertEqual(document.find("main"), [{"id": "main-content", "tabindex": "-1"}])
                self.assertTrue(any(a.get("href") == "#main-content" for a in document.find("a")))
                self.assertFalse(document.find("script"))
                self.assertFalse(document.find("style"))
                for _, attrs in document.elements:
                    self.assertNotIn("style", attrs)
                    self.assertFalse(any(name.startswith("on") for name in attrs))
                self.assertContains(response, 'href="/assets/reference/style.css"')

    def test_existing_stylesheet_is_served_with_keyboard_focus_styles(self) -> None:
        response = self.client.get("/assets/reference/style.css")
        try:
            self.assertEqual(response.status_code, 200)
            css = b"".join(response.streaming_content)
            self.assertIn(b":focus-visible", css)
            self.assertIn(b".skip-link:focus", css)
        finally:
            response.close()

    def test_pages_do_not_offer_editions_private_features_or_published_answers(self) -> None:
        self.one_source()
        for route in ["/", "/help"]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertContains(response, "وليست فتاوى منشورة")
                self.assertFalse(Elements(response.content).find("select"))
                for text in [
                    'name="edition"',
                    "?edition=",
                    SOURCE["edition_key"],
                    SOURCE["title"],
                    SOURCE["source_archive_sha256"],
                    "أحدث الفتاوى",
                    "فتاوى معتمدة",
                    "اطلب فتوى",
                    "تسجيل الدخول",
                    "إنشاء حساب",
                    "إجابة الذكاء الاصطناعي",
                ]:
                    self.assertNotContains(response, text)
        for route in [
            "/fatwas",
            "/accounts/login",
            "/admin/",
            "/api/v1/fatwas",
            "/api/v1/private/cases",
        ]:
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_head_is_supported_without_body(self) -> None:
        for route in ["/", "/help"]:
            with self.subTest(route=route):
                response = self.client.head(route)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"")
                self.assertIn("text/html", response["Content-Type"])

    def test_unsafe_methods_are_rejected_before_catalog_reads_even_with_csrf_enforced(self) -> None:
        client = Client(enforce_csrf_checks=True)
        for route in ["/", "/help", "/fiqh", "/readyz", "/healthz", "/api/v1/fiqh/search"]:
            for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
                with self.subTest(route=route, method=method):
                    response = client.generic(method, route)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
                    self.assertIn("Content-Security-Policy", response)
        self.books.assert_not_called()

    def test_views_also_reject_unsafe_methods_without_middleware(self) -> None:
        factory = RequestFactory()
        for view, route in [(views.home, "/"), (views.help_page, "/help")]:
            for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
                with self.subTest(route=route, method=method):
                    response = view(factory.generic(method, route))
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
        self.books.assert_not_called()

    def test_security_headers_are_applied_to_get_and_head(self) -> None:
        for route in ["/", "/help"]:
            for method in ["get", "head"]:
                with self.subTest(route=route, method=method):
                    response = getattr(self.client, method)(route)
                    self.assertEqual(response["X-Frame-Options"], "DENY")
                    self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                    self.assertEqual(response["Referrer-Policy"], "no-referrer")
                    self.assertEqual(response["Cache-Control"], "no-store")
                    csp = response["Content-Security-Policy"]
                    self.assertIn("default-src 'none'", csp)
                    self.assertIn("form-action 'self'", csp)
                    self.assertNotIn("unsafe-inline", csp)
                    self.assertNotIn("unsafe-eval", csp)

    def test_invalid_hosts_are_rejected_without_catalog_reads(self) -> None:
        for route in ["/", "/help"]:
            response = self.client.get(route, HTTP_HOST="evil.example")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Content-Security-Policy", response)
        self.books.assert_not_called()
