"""Synthetic root navigation with real Django PostgreSQL query compilation.

Cursor fixtures prove bounded SELECTs and ordering, not database execution or
acceptance of the protected source corpus.
"""

from django.test import SimpleTestCase

from apps.reference import services
from apps.reference.query import MAX_OFFSET, InvalidQuery, Page
from tests.integration.api.test_catalog import cursor_rows, edition, heading, values


class RootNavigationTests(SimpleTestCase):
    def test_anchor_locates_sparse_root_positions_with_four_bounded_selects(self):
        source = edition()
        anchor = heading(26, position=260)
        siblings = [heading(i, position=i * 10) for i in range(22, 27)]
        with cursor_rows(
            [values(anchor)], [(24,)], [(25,)], [values(row) for row in siblings]
        ) as sql:
            result = services.root_page(source, Page(20), 26)

        self.assertEqual(result.offset, 20)
        self.assertEqual(result.limit, 20)
        self.assertEqual(result.total, 25)
        self.assertIn(26, [item["id"] for item in result.items])
        self.assertIsNone(result.next_offset)
        self.assertEqual(len(sql.calls), 4)
        self.assertTrue(all(query.lstrip().startswith("SELECT") for query, _ in sql.calls))
        self.assertIn("LIMIT 20 OFFSET 20", sql.calls[-1][0])
        preceding_query, preceding_params = sql.calls[1]
        self.assertIn('"parent_id" IS NULL', preceding_query)
        self.assertIn(source.pk, preceding_params)
        self.assertIn(anchor.position, preceding_params)
        self.assertIn(anchor.source_order, preceding_params)
        self.assertIn(anchor.source_row_id, preceding_params)
        for field in ("position", "source_order", "source_row_id"):
            self.assertIn(f'"{field}" ASC', sql.calls[-1][0])

    def test_unanchored_roots_reuse_existing_paging_and_empty_catalog(self):
        row = heading(3, position=30)
        with cursor_rows([(3,)], [values(row)]) as sql:
            result = services.root_page(edition(), Page(1, 2))
        self.assertEqual(result.items[0]["id"], 3)
        self.assertEqual(result.offset, 2)
        self.assertEqual(len(sql.calls), 2)
        self.assertIn("LIMIT 1 OFFSET 2", sql.calls[-1][0])
        self.assertEqual(services.root_page(None, Page(1)).items, [])

    def test_anchor_is_resolved_in_selected_edition_and_missing_is_not_found(self):
        source = edition(8)
        with cursor_rows([]) as sql, self.assertRaises(services.HeadingNotFound):
            services.root_page(source, Page(), 26)
        self.assertEqual(len(sql.calls), 1)
        self.assertIn(source.pk, sql.calls[0][1])
        self.assertIn(26, sql.calls[0][1])
        with self.assertRaises(services.HeadingNotFound):
            services.root_page(None, Page(), 26)

    def test_nonroot_and_malformed_root_anchors_are_not_found(self):
        for row in (heading(2, 1, 2), heading(2, depth=2), heading(2, edition_id=8)):
            with self.subTest(row=row), cursor_rows([values(row)]) as sql:
                with self.assertRaises(services.HeadingNotFound):
                    services.root_page(edition(), Page(), 2)
            self.assertEqual(len(sql.calls), 1)

    def test_nonzero_offset_with_anchor_is_rejected_before_querying(self):
        with self.assertRaises(InvalidQuery):
            services.root_page(edition(), Page(20, 20), 26)

    def test_computed_anchor_offset_obeys_pagination_bound(self):
        with cursor_rows([values(heading(26))], [(MAX_OFFSET + 1,)]) as sql:
            with self.assertRaises(InvalidQuery):
                services.root_page(edition(), Page(1), 26)
        self.assertEqual(len(sql.calls), 2)

    def test_page_limit_is_validated_before_any_select(self):
        for limit in (0, 101, True):
            with self.subTest(limit=limit), self.assertRaises(InvalidQuery):
                services.root_page(edition(), Page(limit), 26)
