"""HTTP integration with real pure services; database access is forbidden."""

import os
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class WorkbenchViewsTests(SimpleTestCase):
    def get(self, path, **extra):
        return self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_connected_detail_uses_exact_history_source_and_real_comparison(self):
        url = reverse("editorial_workbench:detail", args=["history"])
        response = self.get(url + "?revision=7&before=11&after=4")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.context["case"].record, REVISION_HISTORY_RECORD)
        self.assertEqual(response.context["selected_revision"].number, 7)
        self.assertEqual(response.context["before_revision"].number, 11)
        self.assertEqual(response.context["after_revision"].number, 4)
        for anchor in ("intake", "snapshot", "history", "comparison", "references", "audit"):
            self.assertContains(response, f'id="{anchor}"')
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, "NOT_DEPLOYED")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_revision_identities_are_never_tuple_positions(self):
        url = reverse("editorial_workbench:detail", args=["history"])
        for query, code in (
            ("revision=3", 404),
            ("revision=07", 400),
            ("before=1", 400),
            ("before=7&after=7", 200),
            ("before=3&after=7", 404),
        ):
            with self.subTest(query=query):
                self.assertEqual(self.get(url + "?" + query).status_code, code)

    def test_filters_preserve_selection_and_no_results_is_a_useful_empty_state(self):
        base = reverse("editorial_workbench:index")
        empty = self.get(base + "?q=NO-MATCH-SYNTHETIC")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.context["detail_rows"], ())
        filtered = self.get(base + "?status=blocked")
        self.assertTrue(filtered.context["cases"])
        self.assertTrue(all(case.status == "blocked" for case in filtered.context["cases"]))
        detail = self.get(reverse("editorial_workbench:detail", args=["history"]) + "?q=NO-MATCH")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("q=NO-MATCH", detail.context["return_url"])
        self.assertTrue(all("q=NO-MATCH" in row["url"] for row in detail.context["history_rows"]))

    def test_invalid_queries_fail_before_loading_any_fixture(self):
        from apps.editorial_workbench import views

        with patch.object(views, "build_cases") as build:
            for suffix in (
                "?q=a&q=b",
                "?status=approved",
                "?file=C:/secret",
                "?q=%00",
                "?q=" + "a" * 81,
                "?before=1&after=2",
                "?q=%7f",
                "?q=" + "&q=" * 30,
            ):
                with self.subTest(suffix=suffix):
                    self.assertEqual(
                        self.get(reverse("editorial_workbench:index") + suffix).status_code, 400
                    )
            build.assert_not_called()

    def test_guard_blocks_non_loopback_and_production_without_loading_fixtures(self):
        from apps.editorial_workbench import views

        url = reverse("editorial_workbench:index")
        with patch.object(views, "build_cases") as build:
            for host, peer in (
                ("remote.invalid", "127.0.0.1"),
                ("localhost", "10.0.0.1"),
                ("localhost", ""),
            ):
                self.assertEqual(
                    self.client.get(url, HTTP_HOST=host, REMOTE_ADDR=peer).status_code, 404
                )
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                self.assertEqual(self.get(url).status_code, 404)
            with override_settings(FATWA_PRODUCTION=True):
                self.assertEqual(self.get(url).status_code, 404)
            build.assert_not_called()

    def test_unsafe_methods_and_head(self):
        urls = [
            reverse("editorial_workbench:index"),
            reverse("editorial_workbench:detail", args=["history"]),
            reverse("editorial_workbench:style"),
            reverse("editorial_workbench:stored"),
        ]
        for url in urls:
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url, HTTP_HOST="localhost")
                    self.assertEqual(response.status_code, 405)
            head = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertIn(head.status_code, (200, 404))
            self.assertEqual(head.content, b"")

    def test_unknown_case_and_unavailable_data_have_helpful_recovery(self):
        from apps.editorial_workbench import views
        from apps.editorial_workbench.services import WorkbenchDataError

        missing = self.get(reverse("editorial_workbench:detail", args=["unknown"]))
        self.assertEqual(missing.status_code, 404)
        with patch.object(views, "build_cases", side_effect=WorkbenchDataError("test")):
            response = self.get(reverse("editorial_workbench:index"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, reverse("editorial_workbench:index"), status_code=503)

    def test_source_is_escaped_and_never_becomes_an_external_link(self):
        from apps.editorial_workbench import views
        from apps.editorial_workbench.services import build_cases

        case = replace(
            build_cases()[0],
            question='<script>alert("x")</script>',
            raw_source="<svg onload=alert(1)>",
        )
        with patch.object(views, "build_cases", return_value=(case,)):
            response = self.get(reverse("editorial_workbench:detail", args=[case.key]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, 'href="https://example.invalid')

    def test_intake_without_draft_never_acquires_history_from_another_case(self):
        response = self.get(reverse("editorial_workbench:detail", args=["intake-2"]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["case"].record)
        self.assertEqual(response.context["history_rows"], ())
        self.assertIsNone(response.context["comparison"])
        selected = self.get(
            reverse("editorial_workbench:detail", args=["intake-2"]) + "?revision=1"
        )
        self.assertEqual(selected.status_code, 400)

    def test_stylesheet_is_local_guarded_and_query_free(self):
        url = reverse("editorial_workbench:style")
        response = self.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response["Content-Type"])
        self.assertEqual(self.get(url + "?path=other").status_code, 400)

    def test_stored_audit_is_disabled_without_existing_opt_in(self):
        with patch("apps.intake_workflow.review.load_review_worklist") as read:
            response = self.get(reverse("editorial_workbench:stored"))
        self.assertEqual(response.status_code, 404)
        read.assert_not_called()
