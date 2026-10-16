"""Actual PostgreSQL + Django endpoint evidence, separate from browser acceptance."""
from django.conf import settings
from django.test import TransactionTestCase

from .support import NAMESPACE, TITLE, require_disposable_database, seed_catalog

require_disposable_database()

class SyntheticServiceTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # At this point Django has already selected its test database.
        if not settings.DATABASES["default"]["NAME"].startswith("test_e6_synthetic"):
            raise RuntimeError("E6 test DB required")
        super().setUpClass()

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = "127.0.0.1"
        seed_catalog()

    def test_inventory_is_fabricated_and_complete(self):
        data = self.client.get("/api/v1/fiqh/books").json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["work"]["source_namespace"], NAMESPACE)
        self.assertEqual(data["items"][0]["heading_count"], 47)

    def test_three_search_modes_with_real_database(self):
        for mode, query in [("exact", TITLE), ("literal", TITLE), ("normalized", "كتاب الطهارة")]:
            with self.subTest(mode=mode):
                data = self.client.get("/api/v1/fiqh/search", {"q": query, "mode": mode}).json()
                self.assertEqual([row["id"] for row in data["items"]], [1])
                self.assertEqual(data["items"][0]["title"], TITLE)

    def test_paging_and_filtered_search(self):
        data = self.client.get("/api/v1/fiqh/search", {
            "q": "باب", "root": 1, "depth": 2, "has_children": "false", "limit": 20,
        }).json()
        self.assertEqual(data["total"], 45)
        self.assertEqual(data["next_offset"], 20)
        following = self.client.get("/api/v1/fiqh/search", {"q": "باب", "offset": 20, "limit": 20}).json()
        self.assertFalse({row["id"] for row in data["items"]} & {row["id"] for row in following["items"]})

    def test_ssr_is_real_template_with_detail_and_empty(self):
        self.assertContains(self.client.get("/fiqh?basic=1"), TITLE)
        self.assertContains(self.client.get("/fiqh/nodes/3?basic=1"), "باب اصطناعي للطهارة 01")
        self.assertContains(self.client.get("/fiqh?basic=1&q=غيرموجود"), "لم نعثر")

    def test_invalid_api_queries_are_json(self):
        for query in ["depth=6", "q=x&q=y", "unknown=1", "offset=20001"]:
            response = self.client.get("/api/v1/fiqh/search?" + query)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"], "invalid_query")

    def test_review_retains_missing_invalid_and_unresolved(self):
        for issue, text in [("media_missing", "رابط المقطع ناقص"),
                            ("media_invalid", "رابط المقطع غير صالح"),
                            ("reference_unverified", "SYN-P02")]:
            response = self.client.get("/dev/editorial-preview/pipeline", {"issue": issue}, REMOTE_ADDR="127.0.0.1")
            self.assertContains(response, text)
            self.assertNotContains(response, "<video")
            self.assertNotContains(response, "<audio")

    def test_review_page_detail_return_preserves_query(self):
        response = self.client.get("/dev/editorial-preview/pipeline/SYN-P02?page_size=1&page=2", REMOTE_ADDR="127.0.0.1")
        self.assertContains(response, "page_size=1&amp;page=2")
        self.assertContains(response, "إحالة غير محسومة")

    def test_review_invalid_empty_and_write_rejection(self):
        self.assertContains(self.client.get("/dev/editorial-preview/pipeline?q=غيرموجود", REMOTE_ADDR="127.0.0.1"), "لا توجد سجلات مطابقة")
        self.assertEqual(self.client.get("/dev/editorial-preview/pipeline?page=0", REMOTE_ADDR="127.0.0.1").status_code, 400)
        self.assertEqual(self.client.post("/dev/editorial-preview/pipeline", REMOTE_ADDR="127.0.0.1").status_code, 405)
