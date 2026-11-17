"""Reference-only previews preserve source text and search return state."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceHeading
from apps.reference.services import CatalogPage, CatalogUnavailable, HeadingNotFound
from tests.public_site.section_fixture import seed_sections
from tests.public_site.test_pages import SOURCE, Elements


@override_settings(PUBLIC_SITE_ORIGIN="https://catalog.example")
class ReferencePreviewBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.books = self.enterContext(
            patch(
                "apps.public_site.views.list_books",
                return_value=CatalogPage([SOURCE], 1, 1, 0, None),
            )
        )
        self.enterContext(patch("apps.public_site.views.resolve_edition", return_value=object()))
        self.enterContext(
            patch("apps.public_site.views.roots", return_value=CatalogPage([], 0, 100, 0, None))
        )
        self.enterContext(
            patch(
                "apps.public_site.views.search",
                return_value=CatalogPage([{"id": 32, "title": "عنوان"}], 61, 30, 30, 60),
            )
        )
        self.node = self.enterContext(patch("apps.public_site.views.node", return_value=object()))
        self.path = self.enterContext(
            patch(
                "apps.public_site.views.heading_path",
                return_value=[
                    {"id": 1, "title": "باب", "part": "جزء", "page": 1},
                    {"id": 32, "title": "عُنْوَانٌ أصلي", "part": "جزء أصلي", "page": 42},
                ],
            )
        )

    def test_preview_preserves_return_state_but_reference_link_excludes_query(self):
        params = {
            "q": "عبارة & أصل",
            "mode": "literal",
            "depth": "2",
            "has_children": "false",
            "offset": "30",
            "heading": "32",
        }
        response = self.client.get("/", params)
        self.assertEqual(response.status_code, 200)
        reference = response.context["reference"]
        self.assertEqual(
            parse_qs(urlsplit(reference["url"]).query),
            {"basic": ["1"], "edition": [str(SOURCE["id"])]},
        )
        self.assertEqual(urlsplit(reference["url"]).path, "/fiqh/nodes/32")
        self.assertEqual(
            parse_qs(urlsplit(response.context["reference_return_url"]).query),
            {k: [v] for k, v in params.items() if k != "heading"},
        )
        self.assertContains(response, "عُنْوَانٌ أصلي")
        self.assertContains(response, "الصفحة المطبوعة: 42")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nosnippet")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotContains(response, 'rel="canonical"')
        self.assertNotContains(response, 'property="og:')

    def test_escaped_titles_and_absent_citation_never_invent_page_or_part(self):
        self.path.return_value[-1].update(title="<script>أَصْل</script>", part=None, page=None)
        response = self.client.get("/", {"heading": 32})
        self.assertContains(response, "&lt;script&gt;أَصْل&lt;/script&gt;")
        self.assertContains(response, "الجزء: غير متاح، الصفحة المطبوعة: غير متاحة")
        self.assertFalse(Elements(response.content).find("script"))
        self.assertEqual(response.context["reference_return_url"], "/#roots-title")
        self.assertEqual(response.context["reference"]["path"], ["باب", "<script>أَصْل</script>"])

    def test_bad_or_duplicate_heading_identifier_rejected_before_reads(self):
        for value in ("", "0", "-1", "٣٢", str(2**63), "9" * 100, ["1", "2"]):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/", {"heading": value}).status_code, 400)
        self.books.assert_not_called()
        self.node.assert_not_called()

    def test_missing_heading_404_suppresses_partial_results_and_source(self):
        self.node.side_effect = HeadingNotFound("secret backend detail")
        response = self.client.get("/", {"q": "عنوان", "heading": 999})
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "secret", status_code=404)
        self.assertNotContains(response, SOURCE["work"]["title_original"], status_code=404)
        self.assertNotContains(response, 'id="results-title"', status_code=404)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nosnippet")

    def test_broken_source_path_fails_closed_without_partial_preview(self):
        self.path.side_effect = CatalogUnavailable("secret broken cross-source hierarchy")
        response = self.client.get("/", {"heading": 32})
        self.assertContains(response, "تعذر الوصول")
        self.assertNotContains(response, "secret")
        self.assertNotContains(response, SOURCE["work"]["title_original"])
        self.assertNotContains(response, 'id="reference-title"')

    def test_multiple_sources_never_implicitly_choose_reference(self):
        self.books.return_value = CatalogPage([SOURCE], 2, 1, 0, 1)
        response = self.client.get("/", {"heading": 32})
        self.assertContains(response, "البحث المباشر معطّل")
        self.node.assert_not_called()
        self.path.assert_not_called()


class ReferencePreviewJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Real PostgreSQL 17 or 18 required")
        cls.edition_id = seed_sections()

    def read(self, path="/", params=None):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, params)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 14)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in queries))
        for query in queries:
            for forbidden in ("casework", "requester_tracking", "editorial"):
                self.assertNotIn(forbidden, query["sql"])
        return response

    def test_second_page_preview_and_return_preserve_scope_filters_and_rows(self):
        before = list(ReferenceHeading.objects.order_by("pk").values())
        params = {
            "q": "عنوان مشترك",
            "root": "1",
            "depth": "2",
            "has_children": "false",
            "offset": "30",
        }
        response = self.read(params=params)
        preview_url = response.context["result_rows"][0]["reference_url"]
        self.assertEqual(
            parse_qs(urlsplit(preview_url).query),
            {**{k: [v] for k, v in params.items()}, "mode": ["normalized"], "heading": ["32"]},
        )
        preview = self.read(preview_url)
        self.assertEqual(preview.context["reference"]["title"], "عنوان مشترك 032")
        self.assertEqual(preview.context["reference"]["page"], 32)
        self.assertEqual(
            preview.context["reference"]["path"], ["باب أول اصطناعي", "عنوان مشترك 032"]
        )
        returned = self.read(preview.context["reference_return_url"])
        self.assertEqual(returned.context["results"], response.context["results"])
        self.assertNotIn("reference", returned.context)
        self.assertEqual(before, list(ReferenceHeading.objects.order_by("pk").values()))

    def test_deep_path_and_clean_reference_link_reach_existing_details(self):
        response = self.read(params={"root": 1, "heading": 65, "offset": 60})
        reference = response.context["reference"]
        self.assertEqual(len(reference["path"]), 5)
        self.assertEqual(reference["path"][-1], "فرع خامس")
        self.assertEqual(
            parse_qs(urlsplit(reference["url"]).query),
            {"basic": ["1"], "edition": [str(self.edition_id)]},
        )
        self.assertContains(self.read(reference["url"]), "فرع خامس")

    def test_heading_outside_selected_section_rejected_without_disclosure(self):
        response = self.client.get("/", {"root": 1, "heading": 101})
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "عنوان مشترك خارج الباب", status_code=404)
        self.assertNotContains(response, 'id="results-title"', status_code=404)
        self.assertEqual(self.client.post("/", {"heading": 32}).status_code, 405)
