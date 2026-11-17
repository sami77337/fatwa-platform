"""Real PostgreSQL journey through public search, details and source hierarchy."""

from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from tests.public_site.search_fixture import seed_catalog
from tests.public_site.test_pages import Elements


class PublicSearchJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Real PostgreSQL 17 or 18 required")
        cls.edition_id = seed_catalog()

    def get_readonly(self, path, params=None):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, params)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 12)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in queries))
        for query in queries:
            for forbidden in ("requester_tracking", "casework", "editorial", "intake_workflow"):
                self.assertNotIn(forbidden, query["sql"])
        return response

    def result_links(self, response):
        # Search results precede the separate root list; filter out its one root.
        return [
            a["href"]
            for a in Elements(response.content).find("a")
            if a["href"].startswith("/fiqh/nodes/") and urlsplit(a["href"]).path != "/fiqh/nodes/1"
        ]

    def snapshot(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (ReferenceWork, ReferenceEdition, ReferenceHeading)
        ]

    def test_three_pages_preserve_order_filters_and_database_then_open_detail(self):
        before = self.snapshot()
        params = {"q": "عنوان اصطناعي", "mode": "normalized", "depth": "2", "has_children": "false"}
        response = self.get_readonly("/", params)
        ids = []
        for offset, count in ((0, 30), (30, 30), (60, 1)):
            links = self.result_links(response)
            self.assertEqual(len(links), count)
            ids.extend(int(urlsplit(link).path.rsplit("/", 1)[1]) for link in links)
            for link in links:
                self.assertEqual(
                    parse_qs(urlsplit(link).query),
                    {"basic": ["1"], "edition": [str(self.edition_id)]},
                )
            if offset < 60:
                next_url = response.context["next_results_url"]
                self.assertEqual(
                    parse_qs(urlsplit(next_url).query),
                    {**{k: [v] for k, v in params.items()}, "offset": [str(offset + 30)]},
                )
                response = self.get_readonly(next_url)
        self.assertEqual(ids, list(range(2, 63)))
        self.assertFalse(response.context["next_results_url"])
        detail = self.get_readonly(links[0])
        self.assertContains(detail, "عُنْوَانٌ اصطناعي 062")
        self.assertContains(detail, "جزء اصطناعي")
        self.assertContains(detail, "باب اصطناعي")
        previous = self.get_readonly(response.context["previous_results_url"])
        self.assertEqual(len(self.result_links(previous)), 30)
        self.assertEqual(self.snapshot(), before)

    def test_out_of_range_and_zero_matches_are_distinct_with_real_storage(self):
        response = self.get_readonly("/", {"q": "عنوان", "offset": 90})
        self.assertContains(response, "لا توجد نتائج في هذه الصفحة")
        first = self.get_readonly(response.context["first_results_url"])
        self.assertEqual(len(self.result_links(first)), 30)
        empty = self.get_readonly("/", {"q": "غيرموجود", "offset": 90})
        self.assertContains(empty, "لا توجد عناوين مطابقة")
        self.assertNotContains(empty, "لا توجد نتائج في هذه الصفحة")

    def test_literal_exact_filters_and_new_query_reset(self):
        literal = self.get_readonly("/", {"q": "عُنْوَانٌ", "mode": "literal", "offset": 30})
        self.assertEqual(len(self.result_links(literal)), 30)
        exact = self.get_readonly("/", {"q": "عُنْوَانٌ اصطناعي 062", "mode": "exact"})
        self.assertEqual(len(self.result_links(exact)), 1)
        self.assertEqual(exact.context["result_start"], 1)
        roots_only = self.get_readonly("/", {"q": "عنوان", "depth": 1})
        self.assertEqual(roots_only.context["results"].total, 0)

    def test_only_reference_apps_are_enabled_and_private_routes_stay_closed(self):
        from django.apps import apps

        self.assertFalse(apps.is_installed("apps.casework"))
        self.assertFalse(apps.is_installed("apps.requester_tracking"))
        for route in ("/fatwas", "/api/v1/fatwas", "/api/v1/private/cases"):
            self.assertEqual(self.client.get(route).status_code, 404)
        before = self.snapshot()
        self.assertEqual(self.client.post("/", {"q": "عنوان", "offset": 30}).status_code, 405)
        self.assertEqual(self.snapshot(), before)
