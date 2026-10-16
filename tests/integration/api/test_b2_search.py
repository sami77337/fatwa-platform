"""B2 SQL compilation/contract regressions; synthetic cursors, no database writes.

These exercise actual ORM SQL generation, not PostgreSQL predicate execution.
"""

from django.test import SimpleTestCase

from apps.reference import services
from apps.reference.normalization import normalize_title
from apps.reference.query import MAX_OFFSET, InvalidQuery, Page
from tests.integration.api.test_catalog import cursor_rows, edition, heading, values


class B2SearchTests(SimpleTestCase):
    def setUp(self):
        self.edition = edition()

    def test_count_has_no_child_aggregation_and_page_is_bounded(self):
        rows = [heading(8, source_order=2), heading(3, source_order=9)]
        with cursor_rows([(2,)], [values(row) for row in rows]) as sql:
            result = services.search(self.edition, "كتاب", "normalized", Page(2))
        self.assertEqual(len(sql.calls), 2)
        count, params = sql.calls[0]
        self.assertNotIn("GROUP BY", count)
        self.assertNotIn("COALESCE", count)
        self.assertNotIn("SELECT COUNT(U0", count)
        self.assertEqual(params, (self.edition.pk, "%كتاب%"))
        self.assertIn("COALESCE", sql.calls[1][0])
        self.assertIn("LIMIT 2", sql.calls[1][0])
        self.assertIn('ORDER BY "reference_referenceheading"."source_order" ASC', sql.calls[1][0])
        self.assertEqual([row["id"] for row in result.items], [8, 3])
        self.assertIsNone(result.next_offset)

    def test_empty_and_past_end_skip_row_query_preserving_total_and_offset(self):
        for total, offset in [(0, 0), (3, 3), (3, 4), (3, MAX_OFFSET)]:
            with self.subTest(total=total, offset=offset), cursor_rows([(total,)]) as sql:
                result = services.search(self.edition, "عنوان", "literal", Page(2, offset))
            self.assertEqual(len(sql.calls), 1)
            self.assertEqual((result.items, result.total, result.offset), ([], total, offset))
            self.assertIsNone(result.next_offset)

    def test_empty_normalized_queries_never_scan_catalog(self):
        for text in ["", "   ", "َـ", "\u00a0"]:
            with self.subTest(text=text), cursor_rows() as sql:
                result = services.search(self.edition, text, "normalized", Page())
            self.assertEqual(result.total, 0)
            self.assertEqual(sql.calls, [])

    def test_invalid_search_rejected_before_scope_lookup(self):
        for text, mode in [
            ("x" * 161, "literal"),
            ("ك " * 11, "normalized"),
            ("عنوان\x00", "exact"),
            ("عنوان\n", "literal"),
            ("عنوان\x7f", "normalized"),
            ("", "unknown"),
        ]:
            with self.subTest(text=text, mode=mode), cursor_rows():
                with self.assertRaises(InvalidQuery):
                    services.search(self.edition, text, mode, Page(), 1)

    def test_arabic_matching_modes_bind_literal_values_without_mutating_title(self):
        original = "كِتَابُ الصَّلاةِ إِلَى الفَتَى"
        row = heading()
        row.title_original = original
        row.title_normalized = normalize_title(original)
        for mode, text, expected in [
            ("exact", original, [original]),
            ("literal", "الصَّلاةِ 100%_", ["%الصَّلاةِ%", "%100\\%\\_%"]),
            ("normalized", "إِلَى الـفَتَى", ["%الي%", "%الفتي%"]),
            ("normalized", "أبواب ابواب أَبْوَاب", ["%ابواب%"]),
        ]:
            with self.subTest(mode=mode, text=text), cursor_rows([(1,)], [values(row)]) as sql:
                result = services.search(self.edition, text, mode, Page())
            for token in expected:
                self.assertEqual(sql.calls[-1][1].count(token), 1)
            self.assertEqual(result.items[0]["title"], original)

    def test_deep_scope_checks_ancestor_depths_and_source_in_three_reads(self):
        root, leaf = heading(), heading(5, 4, 5)
        with cursor_rows([values(root)], [(1,)], [values(leaf)]) as sql:
            result = services.search(self.edition, "عنوان", "normalized", Page(1), 1)
        self.assertEqual(len(sql.calls), 3)
        self.assertEqual(result.items[0]["depth"], 5)
        for statement, params in sql.calls[1:]:
            self.assertIn(root.pk, params)
            self.assertIn(5, params)
            self.assertGreaterEqual(statement.count('"depth" ='), 10)
            self.assertNotIn("WITH RECURSIVE", statement)

    def test_anchor_boundary_and_offset_bound_are_checked_before_child_page(self):
        parent, anchor = heading(), heading(3, 1, 2, position=900)
        with cursor_rows([values(anchor)], [(20,)], [(21,)], [values(anchor)]) as sql:
            result = services.child_page(self.edition, parent, Page(20), 3)
        self.assertEqual(len(sql.calls), 4)
        self.assertEqual(result.offset, 20)
        self.assertIsNone(result.next_offset)
        self.assertIn("OFFSET 20", sql.calls[-1][0])
        with cursor_rows([values(anchor)], [(MAX_OFFSET + 1,)]):
            with self.assertRaises(InvalidQuery):
                services.child_page(self.edition, parent, Page(1), 3)


class B2APIValidationTests(SimpleTestCase):
    def test_invalid_search_parameters_do_not_connect_to_database(self):
        for params in [
            {"q": "x" * 161},
            {"q": "ك " * 11},
            {"q": "عنوان\x00"},
            {"q": "عنوان", "offset": "-1"},
            {"limit": "0"},
            {"root": "9223372036854775808"},
            {"root": "١"},
        ]:
            with self.subTest(params=params):
                response = self.client.get("/api/v1/fiqh/search", params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_query")

    def test_search_envelope_and_source_identity_are_unchanged(self):
        selected = edition()
        with cursor_rows([values(selected)], [(0,)]):
            response = self.client.get("/api/v1/fiqh/search", {"q": "غائب", "offset": 2})
        self.assertEqual(response.status_code, 200)
        data = response.json()
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
        self.assertEqual(data["edition"]["source_input_sha256"], selected.source_input_sha256)
        self.assertEqual((data["items"], data["total"], data["offset"]), ([], 0, 2))
