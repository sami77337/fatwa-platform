"""Strict validation and PostgreSQL SQL compilation; no database connections."""

from django.test import SimpleTestCase

from apps.reference import services
from apps.reference.query import InvalidQuery, Page
from tests.integration.api.test_catalog import cursor_rows, edition, heading, values


class C4FilterTests(SimpleTestCase):
    def test_bad_filters_are_json_400_before_database_access(self):
        queries = [
            "depth=",
            "depth=0",
            "depth=6",
            "depth=-1",
            "depth=1.0",
            "depth=١",
            "depth=+1",
            "depth=1%20",
            "depth=1&depth=1",
            "has_children=",
            "has_children=True",
            "has_children=FALSE",
            "has_children=1",
            "has_children=0",
            "has_children=null",
            "has_children=true%20",
            "has_children=true&has_children=false",
            "has_children=true&unknown=1",
            "depth=2&mode=unknown",
        ]
        for query in queries:
            with self.subTest(query=query):
                response = self.client.get("/api/v1/fiqh/search?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_query")
                self.assertIn("application/json", response["Content-Type"])

    def test_service_rejects_wrong_types_even_for_empty_catalog(self):
        for depth, children in [
            (True, None),
            (0, None),
            (6, None),
            ("2", None),
            (None, 0),
            (None, "false"),
        ]:
            with self.subTest(depth=depth, children=children), self.assertRaises(InvalidQuery):
                services.search(None, "", "normalized", Page(), depth=depth, has_children=children)

    def test_child_existence_is_edition_scoped_in_count_and_page_sql(self):
        for children in [True, False]:
            row = heading(2, 1, 2)
            with self.subTest(children=children), cursor_rows([(1,)], [values(row)]) as sql:
                result = services.search(
                    edition(), "كِتاب", "normalized", Page(1), depth=2, has_children=children
                )
            self.assertEqual(result.total, 1)
            for statement, params in sql.calls:
                self.assertIn("EXISTS", statement)
                self.assertIn('U0."edition_id" =', statement)
                self.assertIn('U0."parent_id" =', statement)
                self.assertIn('"depth" =', statement)
                self.assertGreaterEqual(params.count(7), 2)
                self.assertIn("%كتاب%", params)
                self.assertEqual("NOT EXISTS" in statement, not children)
            self.assertNotIn("COALESCE", sql.calls[0][0])

    def test_empty_catalog_retains_response_contract(self):
        with cursor_rows([]):
            response = self.client.get(
                "/api/v1/fiqh/search", {"q": "كتاب", "depth": "5", "has_children": "false"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(response.json()["items"], [])
        self.assertNotIn("depth", response.json())
        self.assertNotIn("has_children", response.json())
