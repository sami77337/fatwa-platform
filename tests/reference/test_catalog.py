"""Real PostgreSQL persistence/API tests using a named synthetic five-row fixture."""
from dataclasses import replace
from unittest.mock import patch

from django.apps import apps
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import Client, SimpleTestCase, TestCase
from django.urls import resolve

from apps.reference.ingest import CatalogConflict, ingest_catalog
from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.records import CatalogSpec, HeadingRecord, InvalidCatalog


def fixture():
    spec = CatalogSpec(
        source_namespace="synthetic", source_book_id="test-622", work_title="مرجع اصطناعي للاختبار",
        madhhab="اختبار", edition_key="test", edition_title="طبعة اختبار", publisher="ناشر اصطناعي",
        source_archive_sha256="a" * 64, source_input_sha256="b" * 64, input_name="s0-five-rows-v1.jsonl",
        expected_rows=5, expected_roots=2, expected_max_depth=3,
    )
    rows = (
        HeadingRecord("synthetic-1", 1, None, 1, 1, 1, 11, "مقدمة", 1, "كِتَابُ أَبْوَابٍ تَجْرِيبِيَّة"),
        HeadingRecord("synthetic-2", 2, 1, 2, 1, 2, 12, "مقدمة", 2, "فَرْعٌ تَجْرِيبِيّ"),
        HeadingRecord("synthetic-3", 3, 1, 3, 2, 2, 13, "مقدمة", 3, "فصل تجريبي 100%_آمن"),
        HeadingRecord("synthetic-4", 4, 2, 4, 1, 3, 14, "مقدمة", 4, '<script>alert("x")</script> عنوان اصطناعي'),
        HeadingRecord("synthetic-5", 5, None, 5, 2, 1, 15, "مقدمة", 5, "فَرْعٌ تَجْرِيبِيّ"),
    )
    return spec, rows


class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("These tests require real PostgreSQL 17 or 18")
        cls.spec, cls.rows = fixture()
        preview = ingest_catalog(cls.spec, cls.rows)
        result = ingest_catalog(cls.spec, cls.rows, dry_run=False, expected_checksum=preview.checksum)
        cls.edition_id = result.edition_id

    def test_dry_run_and_rerun_do_not_write(self):
        before = (ReferenceWork.objects.count(), ReferenceEdition.objects.count(), ReferenceHeading.objects.count())
        preview = ingest_catalog(self.spec, self.rows)
        self.assertTrue(preview.dry_run)
        self.assertTrue(preview.unchanged)
        result = ingest_catalog(self.spec, self.rows, dry_run=False, expected_checksum=preview.checksum)
        self.assertTrue(result.unchanged)
        other = replace(self.spec, source_book_id="new-work")
        self.assertFalse(ingest_catalog(other, self.rows).unchanged)
        self.assertEqual(before, (ReferenceWork.objects.count(), ReferenceEdition.objects.count(), ReferenceHeading.objects.count()))

    def test_commit_requires_exact_preview_and_changed_input_is_rejected(self):
        for checksum in [None, "0" * 64]:
            with self.assertRaises(CatalogConflict):
                ingest_catalog(self.spec, self.rows, dry_run=False, expected_checksum=checksum)
        changed = (replace(self.rows[0], title_original="تعديل اصطناعي"), *self.rows[1:])
        with self.assertRaises(CatalogConflict):
            ingest_catalog(self.spec, changed)
        with self.assertRaises(CatalogConflict):
            ingest_catalog(replace(self.spec, publisher="ناشر آخر"), self.rows)
        self.assertEqual(ReferenceHeading.objects.get(source_row_id=1).title_original, self.rows[0].title_original)

    def test_insertion_is_atomic_even_after_a_partial_batch(self):
        spec = replace(self.spec, source_book_id="rollback-work")
        preview = ingest_catalog(spec, self.rows)
        original = ReferenceHeading.objects.bulk_create
        calls = 0
        def fail_second_batch(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated storage interruption")
            return original(*args, **kwargs)
        with patch("apps.reference.ingest.ReferenceHeading.objects.bulk_create", side_effect=fail_second_batch):
            with self.assertRaises(RuntimeError):
                ingest_catalog(spec, self.rows, dry_run=False, expected_checksum=preview.checksum)
        self.assertFalse(ReferenceWork.objects.filter(source_book_id="rollback-work").exists())
        self.assertEqual(ReferenceHeading.objects.count(), 5)

    def new_heading(self, **changes):
        fields = {
            "edition_id": self.edition_id, "source_id": "new-20", "source_row_id": 20,
            "parent_id": None, "source_order": 20, "position": 20, "depth": 1,
            "source_page_id": 20, "source_part": "اختبار", "source_page_number": 20,
            "title_original": "عنوان جديد اصطناعي", "title_normalized": "عنوان جديد اصطناعي",
        }
        return ReferenceHeading(**{**fields, **changes})

    def test_database_unique_and_orphan_and_root_constraints(self):
        root = ReferenceHeading.objects.get(source_row_id=1)
        invalid = [
            {"source_id": root.source_id}, {"source_row_id": 1}, {"source_order": 1},
            {"position": 1}, {"parent_id": 2**60, "depth": 2}, {"depth": 2},
            {"source_page_number": 0}, {"source_part": ""}, {"title_original": ""},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                self.new_heading(**changes).save()

    def test_cross_edition_parent_and_wrong_depth_are_rejected(self):
        other = replace(self.spec, edition_key="other")
        preview = ingest_catalog(other, self.rows)
        result = ingest_catalog(other, self.rows, dry_run=False, expected_checksum=preview.checksum)
        root = ReferenceHeading.objects.get(edition_id=self.edition_id, source_row_id=1)
        for changes in [{"edition_id": result.edition_id, "parent_id": root.pk, "depth": 2},
                        {"parent_id": root.pk, "depth": 3}]:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                self.new_heading(**changes).save()

    def test_database_snapshots_are_immutable_including_cycles(self):
        root = ReferenceHeading.objects.get(source_row_id=1)
        child = ReferenceHeading.objects.get(source_row_id=2)
        operations = [
            lambda: ReferenceHeading.objects.filter(pk=root.pk).update(parent_id=child.pk),
            lambda: ReferenceHeading.objects.filter(pk=child.pk).update(source_id="changed"),
            lambda: ReferenceEdition.objects.filter(pk=self.edition_id).update(source_input_sha256="c" * 64),
            lambda: ReferenceWork.objects.update(title_original="changed"),
            lambda: ReferenceHeading.objects.filter(source_row_id=4).delete(),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_bad_graph_is_rejected_before_any_orm_write(self):
        changed = (self.rows[0], replace(self.rows[1], parent_source_row_id=999), *self.rows[2:])
        with self.assertNumQueries(0), self.assertRaises(InvalidCatalog):
            ingest_catalog(self.spec, changed)

    def test_positive_navigation_citation_and_breadcrumb(self):
        roots = self.client.get("/api/v1/fiqh/roots").json()
        self.assertEqual([row["id"] for row in roots["items"]], [1, 5])
        self.assertEqual(roots["kind"], "SOURCE_BOOK_TOC_NOT_FATWAS")
        self.assertEqual(roots["edition"]["publisher"], self.spec.publisher)
        node = self.client.get("/api/v1/fiqh/nodes/4").json()
        self.assertEqual([row["id"] for row in node["ancestors"]], [1, 2, 4])
        self.assertEqual(node["node"]["part"], "مقدمة")
        self.assertEqual(node["node"]["page"], 4)
        children = self.client.get("/api/v1/fiqh/nodes/1/children", {"limit": 1}).json()
        self.assertEqual([row["id"] for row in children["items"]], [2])
        self.assertEqual(children["next_offset"], 1)
        next_page = self.client.get("/api/v1/fiqh/nodes/1/children", {"limit": 1, "offset": 1}).json()
        self.assertEqual([row["id"] for row in next_page["items"]], [3])

    def test_search_exact_normalized_and_literal_wildcards(self):
        for q, mode, expected in [
            ("كتاب ابواب", "normalized", [1]), (self.rows[1].title_original, "exact", [2, 5]),
            ("فرع تجريبي", "exact", []), ("100%_", "literal", [3]), ("__", "literal", []),
            ("' OR 1=1 --", "literal", []), ("", "normalized", []),
        ]:
            with self.subTest(q=q, mode=mode):
                response = self.client.get("/api/v1/fiqh/search", {"q": q, "mode": mode})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([row["id"] for row in response.json()["items"]], expected)

    def test_query_limits_duplicates_and_unknown_parameters(self):
        for query in ["limit=101", "offset=-1", "offset=20001", "limit=1&limit=2", "mode=ai", "edition=0", "private_case=1", "q=" + "x" * 161]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/v1/fiqh/search?" + query).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/fiqh/nodes/" + "9" * 100).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/fiqh/nodes/999").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/fiqh/search?q=" + "x" * 5000).status_code, 400)

    def test_editions_are_isolated_and_ambiguity_is_explicit(self):
        other = replace(self.spec, edition_key="other")
        preview = ingest_catalog(other, self.rows)
        result = ingest_catalog(other, self.rows, dry_run=False, expected_checksum=preview.checksum)
        self.assertEqual(self.client.get("/api/v1/fiqh/roots").status_code, 400)
        for edition_id in [self.edition_id, result.edition_id]:
            response = self.client.get("/api/v1/fiqh/roots", {"edition": edition_id})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["edition"]["id"], edition_id)
            self.assertEqual(response.json()["total"], 2)
        response = self.client.get("/fiqh")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اختر الطبعة")
        self.assertNotContains(response, 'class="heading-list"')
        for edition_id in [self.edition_id, result.edition_id]:
            url = f"/fiqh?edition={edition_id}&basic=1"
            self.assertContains(response, url.replace("&", "&amp;"))
            selected = self.client.get(url)
            self.assertEqual(selected.status_code, 200)
            self.assertEqual(selected.context["edition"]["id"], edition_id)
            self.assertEqual(selected.context["results"].total, 2)

    def test_all_unsafe_methods_are_denied_without_queries(self):
        client = Client(enforce_csrf_checks=True)
        for url in ["/", "/fiqh", "/healthz", "/readyz", "/api/v1/fiqh/search", "/api/v1/fiqh/nodes/1", "/api/v1/private/cases", "/admin/", "/api/v1/fatwas/publish"]:
            for method in ["post", "put", "patch", "delete", "options", "trace"]:
                with self.subTest(url=url, method=method), self.assertNumQueries(0):
                    response = getattr(client, method)(url)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
        self.assertEqual(ReferenceHeading.objects.count(), 5)

    def test_no_private_routes_apps_or_payload_keys(self):
        for url in ["/admin/", "/accounts/login", "/api/v1/private/cases", "/api/v1/fatwas", "/api/v1/users", "/api/v1/permissions"]:
            self.assertEqual(self.client.get(url).status_code, 404)
        labels = {model._meta.app_label for model in apps.get_models()}
        self.assertEqual(labels, {"reference"})
        payload = self.client.get("/api/v1/fiqh/roots").json()
        self.assertEqual(set(payload["items"][0]), {"id", "source_id", "parent_id", "title", "depth", "position", "source_order", "children_count", "part", "page", "page_id", "source_entry_number"})
        self.assertNotIn("input_name", payload["edition"])
        self.assertNotIn("ingest_checksum", payload["edition"])

    def test_security_headers_head_host_and_error_redaction(self):
        response = self.client.get("/healthz")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", response["Content-Security-Policy"])
        self.assertEqual(self.client.head("/healthz").content, b"")
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="evil.example").status_code, 400)
        with patch("apps.reference.services.resolve_edition", side_effect=OperationalError("secret-connection-string")):
            response = self.client.get("/api/v1/fiqh/roots")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"secret-connection-string", response.content)

    def test_rtl_template_lazy_fallback_and_escaped_source_text(self):
        response = self.client.get("/fiqh")
        self.assertContains(response, 'lang="ar" dir="rtl"')
        self.assertContains(response, '<details hx-get=')
        self.assertContains(response, 'hx-trigger="toggle once"')
        self.assertContains(response, "وليست فتاوى منشورة")
        self.assertContains(response, 'label for="query"')
        response = self.client.get("/fiqh/nodes/4")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')
        fragment = self.client.get("/fiqh/nodes/1/children", HTTP_HX_REQUEST="true")
        self.assertNotContains(fragment, "<!doctype html>")
        self.assertContains(fragment, self.rows[1].title_original)
        self.assertIn("HX-Request", fragment["Vary"])
        self.assertContains(self.client.get("/fiqh/nodes/1/children"), "<!doctype html>")


    def test_read_query_budgets_are_measured_by_django(self):
        # Small synthetic fixture only; this is not full-source performance evidence.
        with self.assertNumQueries(3):
            self.assertEqual(self.client.get("/api/v1/fiqh/roots").status_code, 200)
        with self.assertNumQueries(4):
            self.assertEqual(self.client.get("/api/v1/fiqh/nodes/1/children").status_code, 200)
        with self.assertNumQueries(3):
            self.assertEqual(self.client.get("/api/v1/fiqh/search", {"q": "تجريبي"}).status_code, 200)
        self.assertEqual(resolve("/api/v1/fiqh/roots").url_name, "api_roots")


class PublicAssetTests(SimpleTestCase):
    def test_public_assets_cannot_read_source_inputs(self):
        response = self.client.get("/assets/reference/style.css")
        self.assertEqual(response.status_code, 200)
        response.close()
        for asset in ["_codex_input/issue.md", "../AGENTS.md", "reference/../../AGENTS.md", "django_htmx/../../AGENTS.md"]:
            self.assertEqual(self.client.get("/assets/" + asset).status_code, 404)
