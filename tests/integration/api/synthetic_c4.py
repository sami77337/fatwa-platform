"""Synthetic predicate execution; run only through run_c4_synthetic.py."""

import unittest

from django.test import Client

from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.normalization import normalize_title


class SyntheticFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = ReferenceWork.objects.create(
            source_namespace="c4-synthetic", source_book_id="c4-v1", title_original="اختبار"
        )
        cls.editions = []
        cls.title = "كِتَابُ أَحْكَامِ الصَّلَاة"
        # Identical source IDs across editions; deliberately different child topology.
        for index in range(2):
            edition = ReferenceEdition.objects.create(
                work=work,
                edition_key=str(index),
                title="اصطناعي",
                publisher="اختبار",
                source_archive_sha256="a" * 64,
                source_input_sha256="b" * 64,
                ingest_checksum="c" * 64,
                input_name="c4-synthetic-v1",
                heading_count=7,
                root_count=2,
                max_depth=5,
            )
            cls.editions.append(edition)
            rows = {}
            for ident, parent, depth in [
                (1, None, 1),
                (2, 1, 2),
                (3, 2, 3),
                (4, 3, 4),
                (5, 4, 5),
                (6, None, 1),
                (7, 6 if index == 0 else 1, 2),
            ]:
                rows[ident] = ReferenceHeading.objects.create(
                    edition=edition,
                    source_id=str(ident),
                    source_row_id=ident,
                    parent=rows.get(parent),
                    depth=depth,
                    source_order=ident,
                    position=ident,
                    source_page_id=ident,
                    source_page_number=ident,
                    source_part="اختبار",
                    title_original=cls.title,
                    title_normalized=normalize_title(cls.title),
                )

    def search(self, **params):
        params.setdefault("edition", self.editions[0].pk)
        params.setdefault("q", "كتاب احكام الصلاة")
        response = Client().get("/api/v1/fiqh/search", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_combinations_and_arabic_modes(self):
        for mode, query in [
            ("normalized", "كـتاب إِحْكَام الصلاة"),
            ("literal", "أَحْكَامِ"),
            ("exact", self.title),
        ]:
            for depth in range(1, 6):
                for children in ["true", "false"]:
                    data = self.search(q=query, mode=mode, depth=depth, has_children=children)
                    expected = [
                        i
                        for i, d, c in [
                            (1, 1, True),
                            (2, 2, True),
                            (3, 3, True),
                            (4, 4, True),
                            (5, 5, False),
                            (6, 1, True),
                            (7, 2, False),
                        ]
                        if d == depth and c == (children == "true")
                    ]
                    self.assertEqual([item["id"] for item in data["items"]], expected)
                    self.assertEqual(data["total"], len(expected))
                    self.assertEqual(data["count"], len(expected))
                    self.assertTrue(all(item["title"] == self.title for item in data["items"]))

    def test_root_scope_includes_root_and_filters_descendants(self):
        self.assertEqual([r["id"] for r in self.search(root=1)["items"]], [1, 2, 3, 4, 5])
        data = self.search(root=1, depth=2, has_children="true")
        self.assertEqual([r["id"] for r in data["items"]], [2])
        self.assertEqual(self.search(root=6, depth=5)["total"], 0)
        for root, status in [(2, 400), (999, 404)]:
            response = Client().get(
                "/api/v1/fiqh/search",
                {
                    "edition": self.editions[0].pk,
                    "q": "",
                    "root": root,
                    "depth": 5,
                    "has_children": "false",
                },
            )
            self.assertEqual(response.status_code, status)

    def test_stable_pagination_and_accurate_totals(self):
        ids = []
        for offset in range(5):
            data = self.search(has_children="true", limit=1, offset=offset)
            self.assertEqual(data["total"], 5)
            self.assertEqual(data["next_offset"], offset + 1 if offset < 4 else None)
            ids.extend(item["id"] for item in data["items"])
        self.assertEqual(ids, [1, 2, 3, 4, 6])
        self.assertEqual(self.search(has_children="true", offset=5)["items"], [])

    def test_edition_isolation_with_repeated_source_ids(self):
        first = self.search(depth=1, has_children="false")
        second = self.search(edition=self.editions[1].pk, depth=1, has_children="false")
        self.assertEqual(first["total"], 0)
        self.assertEqual([r["id"] for r in second["items"]], [6])
        self.assertEqual(self.search(edition=self.editions[1].pk, root=6)["total"], 1)
        self.assertEqual(self.search(root=6)["total"], 2)
        self.assertEqual(Client().get("/api/v1/fiqh/search?q=كتاب&depth=2").status_code, 400)

    def test_empty_matches_and_unchanged_envelope(self):
        data = self.search(q="غائب", depth=5, has_children="false")
        self.assertEqual((data["items"], data["total"], data["next_offset"]), ([], 0, None))
        self.assertEqual(
            set(data),
            {
                "kind",
                "items",
                "total",
                "count",
                "limit",
                "offset",
                "next_offset",
                "query",
                "mode",
                "edition",
            },
        )
        self.assertEqual(self.search(q="َـ", depth=2)["items"], [])
