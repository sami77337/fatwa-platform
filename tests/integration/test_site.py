"""Real PostgreSQL integration: explicit synthetic fixture, no development-site seeding."""

from django.db import connection
from django.test import TestCase

from apps.reference.ingest import ingest_catalog
from apps.reference.records import CatalogSpec, HeadingRecord


class IntegratedSiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Requires PostgreSQL 17/18")
        rows = [HeadingRecord("test-1", 1, None, 1, 1, 1, 1001, "المقدمة", 1, "جذر اختبار")]
        for index in range(25):
            ident = 100 + index
            rows.append(
                HeadingRecord(
                    "test-" + str(ident),
                    ident,
                    1,
                    len(rows) + 1,
                    (index + 1) * 10,
                    2,
                    1000 + ident,
                    "المقدمة",
                    index + 2,
                    "عنوان اختبار " + str(index),
                )
            )
        for ident, parent, depth in [(200, 124, 3), (201, 200, 4), (202, 201, 5)]:
            rows.append(
                HeadingRecord(
                    "test-" + str(ident),
                    ident,
                    parent,
                    len(rows) + 1,
                    1,
                    depth,
                    1000 + ident,
                    "المقدمة",
                    ident,
                    "مسار اختبار",
                )
            )
        rows.append(
            HeadingRecord(
                "test-500",
                500,
                None,
                len(rows) + 1,
                2,
                1,
                1500,
                "المقدمة",
                500,
                "عنوان خارج النطاق",
            )
        )
        cls.spec = CatalogSpec(
            "synthetic",
            "integration-v1",
            "مرجع اصطناعي للاختبار",
            "اختبار",
            "test-v1",
            "طبعة اختبار",
            "ناشر اختبار",
            "a" * 64,
            "b" * 64,
            "integration-30-rows-v1.jsonl",
            len(rows),
            2,
            5,
        )
        preview = ingest_catalog(cls.spec, rows)
        cls.edition = ingest_catalog(
            cls.spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id

    def test_root_scope_search_is_bounded_and_excludes_other_root(self):
        response = self.client.get(
            "/api/v1/fiqh/search", {"edition": self.edition, "q": "عنوان", "root": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 25)
        self.assertNotIn(500, [row["id"] for row in response.json()["items"]])
        self.assertEqual(
            self.client.get("/api/v1/fiqh/search", {"q": "عنوان", "root": 100}).status_code, 400
        )
        self.assertEqual(
            self.client.get("/api/v1/fiqh/search", {"q": "عنوان", "root": 999}).status_code, 404
        )

    def test_anchor_pages_non_contiguous_sibling_positions(self):
        response = self.client.get("/api/v1/fiqh/nodes/1/children", {"limit": 20, "anchor": 124})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["offset"], 20)
        self.assertIn(124, [row["id"] for row in response.json()["items"]])
        self.assertEqual(
            self.client.get("/api/v1/fiqh/nodes/1/children?anchor=500").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/v1/fiqh/nodes/1/children?anchor=124&offset=0").status_code, 400
        )

    def test_integrated_html_and_basic_fallback_have_real_source_metadata(self):
        response = self.client.get("/fiqh/nodes/202")
        self.assertContains(response, 'data-node="202"')
        self.assertContains(response, "reference/catalog.js")
        self.assertContains(response, "المقدمة")
        self.assertContains(response, "test-202")
        self.assertContains(response, 'id="server-catalog"')
        self.assertContains(response, 'lang="ar" dir="rtl"')
        basic = self.client.get("/fiqh/nodes/202?basic=1")
        self.assertNotContains(basic, "reference/catalog.js")
        self.assertContains(basic, 'aria-current="page"')
        self.assertContains(basic, "basic=1")
        search = self.client.get("/fiqh?q=عنوان&limit=1")
        self.assertContains(search, "التالي")
        self.assertNotContains(search, "reference/catalog.js")

    def test_only_integrated_static_modules_are_served(self):
        for name in ["catalog.js", "django-api.mjs", "catalog.css"]:
            response = self.client.get("/assets/reference/" + name)
            self.assertEqual(response.status_code, 200)
            body = b"".join(response.streaming_content)
            self.assertNotIn(b"createMockAdapter", body)
            self.assertNotIn(b"fixture.js", body)
            response.close()
        for name in ["fixture.js", "../../AGENTS.md", "book622.py"]:
            self.assertEqual(self.client.get("/assets/reference/" + name).status_code, 404)

    def test_new_get_parameters_do_not_open_write_methods(self):
        for route in [
            "/api/v1/fiqh/search?root=1",
            "/api/v1/fiqh/nodes/1/children?anchor=124",
            "/fiqh?basic=1",
        ]:
            for method in ["post", "put", "patch", "delete"]:
                with self.assertNumQueries(0):
                    self.assertEqual(getattr(self.client, method)(route).status_code, 405)

    def test_deep_search_result_path_and_search_paging(self):
        detail = self.client.get("/api/v1/fiqh/nodes/202").json()
        self.assertEqual([row["id"] for row in detail["ancestors"]], [1, 124, 200, 201, 202])
        first = self.client.get("/api/v1/fiqh/search?q=عنوان&root=1&limit=20").json()
        last = self.client.get("/api/v1/fiqh/search?q=عنوان&root=1&limit=20&offset=20").json()
        self.assertEqual(first["next_offset"], 20)
        self.assertEqual(last["next_offset"], None)
        self.assertEqual(len(last["items"]), 5)
        self.assertFalse(
            {row["id"] for row in first["items"]} & {row["id"] for row in last["items"]}
        )
