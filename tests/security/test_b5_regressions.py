"""B5: database-forbidden regressions; mocks are explicitly scoped per test."""

from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, SimpleTestCase

from apps.reference import services
from apps.reference.query import Page


class B5PublicRegressionTests(SimpleTestCase):
    databases = set()

    def test_parameter_overflow_keeps_api_json_error_schema(self):
        # Django's query-parser limit must preserve the public JSON error contract.
        query = "&".join(f"field{i}=x" for i in range(17))
        response = self.client.get("/api/v1/fiqh/books?" + query)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {
            "kind": services.KIND, "error": "invalid_query",
        })

    def test_synthetic_source_attribution_has_exact_public_fields(self):
        public = dict(
            pk=7, edition_key="b5-synthetic-not-owner-source", title="Synthetic edition",
            publisher="Synthetic publisher", heading_count=1, root_count=1, max_depth=1,
            source_archive_sha256="a" * 64, source_input_sha256="b" * 64,
        )
        work = dict(source_namespace="b5", source_book_id="synthetic",
                    title_original="Synthetic reference", madhhab="synthetic")
        marker = "B5_SYNTHETIC_PRIVATE_NEVER_PUBLIC"
        edition = SimpleNamespace(**public, work=SimpleNamespace(**work, requester=marker),
                                  input_name=marker, private_case=marker)
        result = services.edition_data(edition)
        expected = {key: value for key, value in public.items() if key != "pk"}
        self.assertEqual(result, {"id": 7, **expected, "work": work})
        self.assertNotIn(marker, str(result))

    def test_invalid_schema_is_rejected_before_any_database_access(self):
        cases = {
            "/api/v1/fiqh/books": ["limit=0", "limit=101", "offset=20001", "limit=+1"],
            "/api/v1/fiqh/roots": ["edition=0", "edition=1&edition=2", "edition=١"],
            "/api/v1/fiqh/nodes/1": ["edition=-1", "pk=1", "edition=1&requester=x"],
            "/api/v1/fiqh/nodes/1/children": ["anchor=1&offset=0", "anchor=0"],
            "/api/v1/fiqh/search": [
                "mode=regex", "q=%00", "q=%7f", "q=" + "x" * 161,
                "q=" + "+".join(["x"] * 11), "root=0", "q=x&q=y",
            ],
            "/fiqh": ["basic=0", "mode=regex", "requester=x"],
            "/healthz": ["callback=x"],
            "/api/v1/status": ["private=true"],
        }
        for route, queries in cases.items():
            for query in queries:
                with self.subTest(route=route, query=query):
                    response = self.client.get(route + "?" + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertNotIn(b"Traceback", response.content)

    def test_mocked_database_failure_is_redacted_through_real_middleware(self):
        marker = "B5_SYNTHETIC_PRIVATE_password_path"
        with patch.object(services, "list_books", side_effect=DatabaseError(marker)):
            for route in ["/api/v1/fiqh/books", "/api/v1/status", "/fiqh"]:
                with self.subTest(route=route):
                    response = self.client.get(route)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn(marker.encode(), response.content)
                    self.assertEqual(response["Cache-Control"], "no-store")

    def test_foreign_edition_heading_is_rejected_before_child_or_path_reads(self):
        edition = SimpleNamespace(pk=1)
        foreign = SimpleNamespace(edition_id=2)
        for operation in [
            lambda: services.children(edition, foreign, Page()),
            lambda: services.child_page(edition, foreign, Page(), 1),
            lambda: services.heading_path(edition, foreign),
        ]:
            with self.subTest(operation=operation):
                with self.assertRaises(services.CatalogUnavailable):
                    operation()

    def test_mocked_foreign_ancestor_is_never_serialized(self):
        # Real path algorithm and projections; only parent lookup is simulated.
        child = SimpleNamespace(
            edition_id=1, pk=11, depth=2, parent_id=22, parent_source_row_id=7,
        )
        foreign = SimpleNamespace(edition_id=2, pk=22, depth=1)
        with patch.object(services, "node", return_value=foreign) as lookup:
            with patch.object(services, "heading_data", return_value={"id": 9}) as project:
                with self.assertRaises(services.CatalogUnavailable):
                    services.heading_path(SimpleNamespace(pk=1), child)
                lookup.assert_called_once_with(SimpleNamespace(pk=1), 7)
                project.assert_called_once_with(child)

    def test_csrf_origin_and_method_override_cannot_activate_writes(self):
        client = Client(enforce_csrf_checks=True)
        for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
            for route in ["/", "/help", "/readyz", "/api/v1/status", "/missing"]:
                with self.subTest(method=method, route=route):
                    response = client.generic(
                        method, route, data=b'{"requester":"B5_SYNTHETIC"}',
                        content_type="application/json", HTTP_ORIGIN="https://foreign.invalid",
                        HTTP_X_HTTP_METHOD_OVERRIDE="GET",
                    )
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
                    self.assertNotIn("Access-Control-Allow-Origin", response)
                    self.assertFalse(response.cookies)

    def test_disabled_sensitive_get_routes_have_no_public_surface(self):
        for route in [
            "/api/v1/cases", "/api/v1/users", "/api/v1/fatwas",
            "/api/v1/publish", "/api/v1/ai", "/api/v1/telegram", "/media/private.json",
        ]:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 404)
