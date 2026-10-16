"""Real Django query compilation/materialization with explicitly synthetic cursor rows.

No database is created or connected. These tests do NOT prove PostgreSQL execution,
source acceptance, trigger behavior, query plans, or real-source performance.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from django.db import OperationalError, connections
from django.test import RequestFactory, SimpleTestCase

from apps.reference import services, views
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.normalization import normalize_title
from apps.reference.query import MAX_OFFSET, InvalidQuery, Page


def edition(ident=7):
    work = ReferenceWork(
        id=11,
        source_namespace="synthetic",
        source_book_id="a2-cursor-v1",
        title_original="مرجع اصطناعي A2",
        madhhab="اختبار",
    )
    return ReferenceEdition(
        id=ident,
        work=work,
        edition_key="a2-" + str(ident),
        title="طبعة اختبار",
        publisher="ناشر اختبار",
        source_archive_sha256="a" * 64,
        source_input_sha256="b" * 64,
        input_name="a2-cursor-rows-v1",
        ingest_checksum="c" * 64,
        heading_count=31,
        root_count=2,
        max_depth=5,
        ingested_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
    )


def heading(ident=1, parent=None, depth=1, position=1, source_order=None, edition_id=7):
    row = ReferenceHeading(
        id=1000 + ident,
        edition_id=edition_id,
        source_id="a2-" + str(ident),
        source_row_id=ident,
        parent_id=None if parent is None else 1000 + parent,
        depth=depth,
        position=position,
        source_order=source_order or ident,
        source_page_id=2000 + ident,
        source_part="المقدمة",
        source_page_number=ident,
        source_entry_number=None,
        title_original="كِتَابٌ 100%_آمن <عنوان>",
        title_normalized=normalize_title("كِتَابٌ 100%_آمن <عنوان>"),
    )
    row.parent_source_row_id = parent
    row.children_count = 0
    return row


def values(row):
    result = [getattr(row, field.attname) for field in row._meta.concrete_fields]
    if isinstance(row, ReferenceHeading):
        result.extend([row.parent_source_row_id, row.children_count])
    elif isinstance(row, ReferenceEdition):
        result.extend(getattr(row.work, field.attname) for field in row.work._meta.concrete_fields)
    return tuple(result)


class CursorRows:
    """Canned DB-API result sets: Django still builds SQL and hydrates model objects."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def cursor(self):
        owner = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def execute(self, sql, params=()):
                if not sql.lstrip().upper().startswith("SELECT"):
                    raise AssertionError("Only SELECT is allowed in A2 cursor fakes")
                owner.calls.append((sql, tuple(params or ())))
                if not owner.batches:
                    raise AssertionError("Unexpected ORM read: " + sql)
                self.rows = list(owner.batches.pop(0))

            def fetchone(self):
                return self.rows.pop(0) if self.rows else None

            def fetchmany(self, size):
                rows, self.rows = self.rows[:size], self.rows[size:]
                return rows

            def close(self):
                pass

        return Cursor()


@contextmanager
def cursor_rows(*batches):
    fake = CursorRows(batches)
    # Patch the concrete wrapper, not Django's proxy: proxy restoration can
    # discard SimpleTestCase's database-access guard during class teardown.
    with patch.object(connections["default"], "cursor", fake.cursor):
        yield fake
    if fake.batches:
        raise AssertionError("Unused cursor result sets")


class PaginationTests(SimpleTestCase):
    def test_bounds_and_continuation_never_advertise_invalid_offsets(self):
        self.assertEqual(Page(20).next_offset(21), 20)
        self.assertIsNone(Page(20).next_offset(20))
        self.assertIsNone(Page(100, MAX_OFFSET).next_offset(MAX_OFFSET + 101))
        self.assertEqual(Page(100, MAX_OFFSET - 100).next_offset(MAX_OFFSET + 1), MAX_OFFSET)
        for args in [(0, 0), (101, 0), (20, -1), (20, MAX_OFFSET + 1), (1.5, 0), (True, 0)]:
            with self.subTest(args=args), self.assertRaises(InvalidQuery):
                Page(*args)


class ORMReadTests(SimpleTestCase):
    def setUp(self):
        self.edition = edition()

    def test_single_empty_and_ambiguous_edition_resolution_use_bounded_inventory(self):
        for rows, expected in [([], None), ([values(self.edition)], self.edition.pk)]:
            with self.subTest(expected=expected), cursor_rows(rows) as fake:
                resolved = services.resolve_edition(None)
                self.assertEqual(resolved.pk if resolved else None, expected)
                self.assertIn("LIMIT 2", fake.calls[0][0])
        with cursor_rows([values(self.edition), values(edition(8))]):
            with self.assertRaises(InvalidQuery):
                services.resolve_edition(None)
        with cursor_rows([]), self.assertRaises(services.HeadingNotFound):
            services.resolve_edition(99)
        with cursor_rows([values(edition(8))]):
            self.assertEqual(services.resolve_edition(8).pk, 8)

    def test_root_pages_use_stable_order_and_bounded_sql_slices(self):
        roots = [heading(1, position=10), heading(20, position=30)]
        with cursor_rows([(2,)], [values(roots[0])], [(2,)], [values(roots[1])]) as fake:
            first = services.roots(self.edition, Page(1))
            last = services.roots(self.edition, Page(1, 1))
        self.assertEqual([first.items[0]["id"], last.items[0]["id"]], [1, 20])
        self.assertEqual(first.next_offset, 1)
        self.assertIsNone(last.next_offset)
        for sql, params in [fake.calls[1], fake.calls[3]]:
            self.assertIn('"parent_id" IS NULL', sql)
            self.assertIn('"position" ASC', sql)
            self.assertIn('"source_order" ASC', sql)
            self.assertIn('"source_row_id" ASC', sql)
            self.assertIn("LIMIT 1", sql)
            self.assertIn(self.edition.pk, params)
        self.assertIn("OFFSET 1", fake.calls[3][0])

    def test_every_breadcrumb_depth_uses_at_most_four_parent_reads(self):
        chain = [heading(i, None if i == 1 else i - 1, i) for i in range(1, 6)]
        for depth in range(1, 6):
            batches = [[values(row)] for row in reversed(chain[:depth])]
            with self.subTest(depth=depth), cursor_rows(*batches) as fake:
                current = services.node(self.edition, depth)
                trail = services.heading_path(self.edition, current)
                self.assertEqual([item["id"] for item in trail], list(range(1, depth + 1)))
                self.assertEqual(len(fake.calls), depth)
                self.assertTrue(all(self.edition.pk in params for _, params in fake.calls))
        self.assertEqual(trail[-1]["title"], chain[-1].title_original)
        self.assertEqual(trail[-1]["part"], "المقدمة")

    def test_malformed_paths_fail_closed(self):
        current = heading(2, 1, 2)
        wrong_parent = heading(1)
        wrong_parent.pk = 999
        with patch.object(services, "node", return_value=wrong_parent):
            with self.assertRaises(services.CatalogUnavailable):
                services.heading_path(self.edition, current)
        wrong_parent = heading(1, depth=2)
        with patch.object(services, "node", return_value=wrong_parent):
            with self.assertRaises(services.CatalogUnavailable):
                services.heading_path(self.edition, current)
        for row in [heading(1, depth=2), heading(1, edition_id=8), heading(1, 2, 1)]:
            with self.subTest(row=row), self.assertRaises(services.CatalogUnavailable):
                services.heading_path(self.edition, row)
        with patch.object(services, "node", side_effect=services.HeadingNotFound):
            with self.assertRaises(services.CatalogUnavailable):
                services.heading_path(self.edition, current)

    def test_empty_search_still_validates_missing_or_nonroot_scope(self):
        for text in ["", "   ", "َـ"]:
            with self.subTest(text=text), cursor_rows([]):
                with self.assertRaises(services.HeadingNotFound):
                    services.search(self.edition, text, "normalized", Page(), 999)
            with cursor_rows([values(heading(2, 1, 2))]):
                with self.assertRaises(InvalidQuery):
                    services.search(self.edition, text, "normalized", Page(), 2)
        with cursor_rows([values(heading())]) as fake:
            self.assertEqual(services.search(self.edition, "", "normalized", Page(), 1).total, 0)
            self.assertEqual(len(fake.calls), 1)
        with self.assertRaises(services.HeadingNotFound):
            services.search(None, "", "normalized", Page(), 1)

    def test_scoped_search_binds_root_pk_and_every_ancestor_edition(self):
        root, leaf = heading(), heading(5, 4, 5)
        with cursor_rows([values(root)], [(1,)], [values(leaf)]) as fake:
            page = services.search(self.edition, "100%_", "literal", Page(20), 1)
        sql, params = fake.calls[-1]
        self.assertIn(root.pk, params)
        self.assertGreaterEqual(params.count(self.edition.pk), 6)
        self.assertIn("100\\%\\_", " ".join(str(value) for value in params))
        self.assertNotIn("100%_", sql)
        self.assertIn("LIMIT 20", sql)
        self.assertNotIn("WITH RECURSIVE", sql.upper())
        self.assertEqual(page.items[0]["id"], 5)
        self.assertEqual(page.items[0]["title"], leaf.title_original)

    def test_exact_and_normalized_search_preserve_original_projection(self):
        row = heading()
        for text, mode in [(row.title_original, "exact"), ("كِتَابٌ أَبْوَابٍ", "normalized")]:
            with self.subTest(mode=mode), cursor_rows([(1,)], [values(row)]) as fake:
                result = services.search(self.edition, text, mode, Page(20))
                sql, params = fake.calls[-1]
                self.assertEqual(result.items[0]["title"], row.title_original)
                if mode == "exact":
                    self.assertIn(text, params)
                else:
                    self.assertIn("%كتاب%", params)
                    self.assertIn("%ابواب%", params)
                self.assertNotIn(text, sql)
        with cursor_rows([(0,)]):
            self.assertEqual(services.search(self.edition, "absent", "literal", Page()).items, [])

    def test_anchored_children_count_preceding_rows_not_source_positions(self):
        parent, anchor = heading(), heading(26, 1, 2, position=260)
        siblings = [heading(i, 1, 2, position=i * 10) for i in range(22, 27)]
        with cursor_rows(
            [values(anchor)], [(24,)], [(25,)], [values(row) for row in siblings]
        ) as fake:
            page = services.child_page(self.edition, parent, Page(20), 26)
        self.assertEqual(page.offset, 20)
        self.assertIn(26, [row["id"] for row in page.items])
        self.assertIsNone(page.next_offset)
        self.assertIn("OFFSET 20", fake.calls[-1][0])
        self.assertIn(parent.pk, fake.calls[1][1])
        self.assertIn(anchor.position, fake.calls[1][1])
        with cursor_rows([values(heading(30, 20, 2))]):
            with self.assertRaises(services.HeadingNotFound):
                services.child_page(self.edition, parent, Page(), 30)
        with self.assertRaises(InvalidQuery):
            services.child_page(self.edition, parent, Page(20, 20), 26)
        with self.assertRaises(services.CatalogUnavailable):
            services.children(self.edition, heading(1, edition_id=8), Page())


class ViewContractTests(SimpleTestCase):
    def test_views_themselves_reject_unsafe_methods_before_any_database_work(self):
        factory = RequestFactory()
        targets = [
            (views.api_books, {}),
            (views.api_roots, {}),
            (views.api_search, {}),
            (views.api_node, {"ident": 1}),
            (views.api_children, {"ident": 1}),
            (views.catalog, {}),
            (views.branch, {"ident": 1}),
            (views.health, {}),
            (views.ready, {}),
            (views.status, {}),
            (views.public_asset, {"asset": "reference/style.css"}),
        ]
        for view, kwargs in targets:
            for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
                with self.subTest(view=view.__name__, method=method):
                    response = view(factory.generic(method, "/"), **kwargs)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(
                        set(response["Allow"].replace(" ", "").split(",")), {"GET", "HEAD"}
                    )

    def test_invalid_parameters_return_400_before_edition_or_database_access(self):
        routes = [
            "/api/v1/fiqh/roots?limit=101",
            "/api/v1/fiqh/roots?offset=20001",
            "/api/v1/fiqh/search?root=0",
            "/api/v1/fiqh/search?root=x",
            "/api/v1/fiqh/search?root=1&root=2",
            "/api/v1/fiqh/search?mode=bad",
            "/api/v1/fiqh/nodes/1/children?anchor=2&offset=0",
            "/api/v1/fiqh/nodes/1/children?anchor=0",
            "/api/v1/fiqh/nodes/1/children?limit=101",
            "/fiqh?edition=x",
            "/fiqh?anchor=2",
            "/fiqh/nodes/1?anchor=2&offset=0",
            "/healthz?unexpected=1",
            "/readyz?unexpected=1",
        ]
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 400)

    def test_database_and_hierarchy_errors_are_redacted(self):
        for error in [
            OperationalError("private-connection-detail"),
            services.CatalogUnavailable("private-detail"),
        ]:
            with patch.object(services, "resolve_edition", side_effect=error):
                response = self.client.get("/api/v1/fiqh/roots")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"], "catalog_unavailable")
                self.assertNotIn(b"private", response.content)
        with patch.object(services, "resolve_edition", side_effect=services.HeadingNotFound):
            self.assertEqual(self.client.get("/api/v1/fiqh/nodes/999").status_code, 404)

    def test_single_source_routes_need_no_edition_parameter(self):
        row, selected = heading(), edition()
        with cursor_rows([values(selected)], [(1,)], [values(row)]):
            response = self.client.get("/api/v1/fiqh/roots?limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["edition"]["id"], selected.pk)
        self.assertEqual(response.json()["items"][0]["title"], row.title_original)
        with (
            patch.object(
                services,
                "list_books",
                return_value=services.CatalogPage(
                    [services.edition_data(selected)],
                    1,
                    100,
                    0,
                    None,
                ),
            ),
            patch.object(services, "resolve_edition", return_value=selected),
        ):
            with cursor_rows([(1,)], [values(row)]):
                context = views._html_context(RequestFactory().get("/fiqh"))
        self.assertTrue(context["single_source"])
        self.assertFalse(context["edition_selection_required"])
        self.assertEqual(context["edition"]["id"], selected.pk)

    def test_ambiguous_html_content_fails_closed_but_root_chooser_is_available(self):
        inventory = services.CatalogPage(
            [services.edition_data(edition()), services.edition_data(edition(8))], 2, 100, 0, None
        )
        with patch.object(services, "list_books", return_value=inventory):
            response = self.client.get("/fiqh")
            self.assertEqual(response.status_code, 200)
            for route in ["/fiqh?q=عنوان", "/fiqh/nodes/1", "/fiqh?offset=1"]:
                with self.subTest(route=route):
                    self.assertEqual(self.client.get(route).status_code, 400)

    def test_basic_anchor_uses_effective_page_for_previous_and_next_links(self):
        selected, parent = edition(), heading()
        inventory = services.CatalogPage([services.edition_data(selected)], 1, 100, 0, None)
        page = services.CatalogPage([services.heading_data(heading(26, 1, 2))], 45, 20, 20, 40)
        with (
            patch.object(services, "list_books", return_value=inventory),
            patch.object(
                services,
                "resolve_edition",
                return_value=selected,
            ),
            patch.object(services, "node", return_value=parent),
            patch.object(
                services,
                "child_page",
                return_value=page,
            ) as children,
        ):
            response = self.client.get("/fiqh/nodes/1?basic=1&anchor=26&limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"offset=0", response.content)
        self.assertIn(b"offset=40", response.content)
        self.assertEqual(children.call_args.args, (selected, parent, Page(20), 26))

    def test_head_is_empty_with_same_json_headers_and_status(self):
        response = self.client.head("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertIn("application/json", response["Content-Type"])
        self.assertEqual(response["Cache-Control"], "no-store")
        response = self.client.get("/healthz")
        self.assertTrue(json.loads(response.content)["read_only"])
