"""E4 real PostgreSQL predicates/SSR navigation, disposable synthetic DB only.

Explicit label for E5: tests.integration.ui.test_e4_postgres
The existing B6 tests/integration/ui label also discovers these tests.
"""

import json
from time import perf_counter
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.normalization import normalize_title
from tests.integration.api.test_e4_catalog import Links


class E4PostgreSQLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.title = "كِتَابُ أَحْكَامِ الصَّلَاة"
        work = ReferenceWork.objects.create(source_namespace="synthetic", source_book_id="e4-wave6",
                                           title_original="مرجع اصطناعي E4", madhhab="اختبار")
        cls.editions = []
        cls.topology = [(1, None, 1)] + [(i, 1, 2) for i in range(2, 27)] + [
            (27, 26, 3), (28, 27, 4), (29, 28, 5), (90, None, 1)]
        for index in range(2):
            edition = ReferenceEdition.objects.create(work=work, edition_key=f"e4-{index}",
                title="طبعة داخلية", publisher="ناشر داخلي", source_archive_sha256="a" * 64,
                source_input_sha256="b" * 64, ingest_checksum="c" * 64, input_name="synthetic-e4",
                heading_count=30, root_count=2, max_depth=5)
            cls.editions.append(edition)
            rows = {}
            for ident, parent, depth in sorted(cls.topology, key=lambda row: (row[2], row[0])):
                if index == 1 and ident == 2:
                    parent = 90
                rows[ident] = ReferenceHeading.objects.create(edition=edition, source_id=f"e4-{ident}",
                    source_row_id=ident, parent=rows.get(parent), depth=depth,
                    position=ident * 10, source_order=ident, source_page_id=ident,
                    source_page_number=ident, source_part="جزء اصطناعي",
                    title_original=cls.title, title_normalized=normalize_title(cls.title))

    def params(self, **changes):
        return {"edition": self.editions[0].pk, "basic": "1", "limit": 100, **changes}

    def api(self, params):
        return self.client.get("/api/v1/fiqh/search", {k: v for k, v in params.items() if k != "basic"})

    def test_modes_filter_only_predicates_match_api_and_ssr(self):
        self.assertEqual(connection.vendor, "postgresql")
        for mode, query in [("normalized", "كـتاب إِحْكَام الصلاة"),
                            ("literal", "أَحْكَامِ"), ("exact", self.title)]:
            for text in (query, "", "   "):
                for root in (None, 1, 90):
                    for depth in (None, 1, 2, 3, 4, 5):
                        for children in (None, True, False):
                            if not text.strip() and root is None and depth is None and children is None:
                                continue  # Blank unfiltered search remains empty; catalog defaults to roots.
                            with self.subTest(mode=mode, text=text, root=root, depth=depth, children=children):
                                params = self.params(q=text, mode=mode)
                                for key, value in (("root", root), ("depth", depth),
                                                   ("has_children", None if children is None else str(children).lower())):
                                    if value is not None:
                                        params[key] = value
                                expected = [ident for ident, parent, level in self.topology
                                    if (root is None or (root == 1 and ident != 90) or (root == 90 and ident == 90))
                                    and (depth is None or depth == level)
                                    and (children is None or children == (ident in {1, 26, 27, 28}))]
                                response = self.api(params)
                                self.assertEqual(response.status_code, 200)
                                data = response.json()
                                self.assertEqual([r["id"] for r in data["items"]], expected)
                                self.assertEqual(data["total"], len(expected))
                                self.assertTrue(all(r["title"] == self.title for r in data["items"]))
                                html = self.client.get("/fiqh", params)
                                self.assertEqual(html.status_code, 200)
                                self.assertEqual([r["id"] for r in html.context["results"].items], expected)
                                self.assertNotContains(html, "طبعة داخلية")

    def test_paging_deep_links_no_results_and_source_isolation(self):
        params = self.params(q="", root=1, depth=2, has_children="false", limit=20)
        first = self.api(params).json()
        params["offset"] = first["next_offset"]
        second = self.api(params).json()
        self.assertEqual([r["id"] for r in first["items"] + second["items"]], list(range(2, 26)))
        self.assertIsNone(second["next_offset"])
        for _ in range(2):  # The same URL reloads without session state.
            response = self.client.get("/fiqh", params)
            self.assertEqual([r["id"] for r in response.context["results"].items], list(range(22, 26)))
            urls = Links(response.content.decode()).hrefs
            previous = next(href for href in urls if "offset=0" in href)
            self.assertEqual(parse_qs(urlsplit(previous).query)["has_children"], ["false"])
        self.assertEqual(self.api(self.params(q="غائب", depth=2)).json()["total"], 0)
        self.assertEqual(self.api(self.params(q="َـ", depth=2)).json()["total"], 0)
        self.assertEqual(self.api(self.params(q="", root=90)).json()["total"], 1)
        second_source = self.params(q="", root=90, edition=self.editions[1].pk)
        self.assertEqual([r["id"] for r in self.api(second_source).json()["items"]], [2, 90])
        self.assertEqual(self.client.get("/api/v1/fiqh/search?depth=2").status_code, 400)
        for root, status in ((2, 400), (999, 404)):
            self.assertEqual(self.api(self.params(q="", root=root)).status_code, status)
        detail = self.client.get("/fiqh/nodes/29", self.params())
        self.assertEqual([r["id"] for r in detail.context["ancestors"]], [1, 26, 27, 28, 29])
        self.assertEqual(self.client.head("/fiqh", self.params(root=1, depth=2)).content, b"")

    def test_bounded_query_counts_and_observed_synthetic_latency(self):
        params = self.params(q="", root=1, depth=2, has_children="false", limit=20)
        samples = {}
        for label, get in (("api", lambda: self.api(params)),
                           ("ssr", lambda: self.client.get("/fiqh", params))):
            durations, counts = [], []
            for _ in range(5):
                start = perf_counter()
                with CaptureQueriesContext(connection) as captured:
                    response = get()
                durations.append(round((perf_counter() - start) * 1000, 3))
                counts.append(len(captured))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(captured), 4 if label == "api" else 6)
                self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in captured))
            samples[label] = {"queries": counts, "wall_ms": durations}
        print("E4_SYNTHETIC_MEASUREMENTS " + json.dumps(samples, sort_keys=True))
