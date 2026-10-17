"""Open E4 defect reproducer. RED at the pinned baseline; never expectedFailure."""
from django.test import TransactionTestCase

from .support import require_disposable_database, seed_catalog

require_disposable_database()


class CatalogConsistencyRegressions(TransactionTestCase):
    def setUp(self):
        seed_catalog()

    def test_filter_only_api_and_ssr_have_same_result_set(self):
        params = {"q": "", "depth": "2", "has_children": "false", "limit": "20"}
        api = self.client.get("/api/v1/fiqh/search", params)
        ssr = self.client.get("/fiqh", {**params, "basic": "1"})
        self.assertEqual(api.status_code, 200)
        self.assertEqual(ssr.status_code, 200)
        self.assertEqual(
            [row["id"] for row in api.json()["items"]],
            [row["id"] for row in ssr.context["results"].items],
            "API and SSR disagree for the same empty-query filter; visible filters must not be ignored",
        )
