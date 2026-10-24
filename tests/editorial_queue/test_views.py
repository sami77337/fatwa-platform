"""Connected real service rendering and read-only development access guards."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_queue import views
from apps.editorial_queue.services import QueueCatalog, build_queue
from apps.editorial_workbench.services import WorkbenchDataError
from apps.revision_core.revision_history import HistoryDataError


class NavigationParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class QueueViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_list_is_rtl_connected_and_has_multiple_questions_and_status_indicators(self):
        response = self.get(reverse("editorial_queue:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 20)
        self.assertEqual(len(response.context["rows"]), 20)
        for row in response.context["rows"]:
            self.assertContains(response, row["url"])
        for marker in (
            'lang="ar"',
            'dir="rtl"',
            'href="#main-content"',
            'for="status"',
            'for="refs"',
        ):
            self.assertContains(response, marker)
        self.assertContains(response, "NOT_DEPLOYED")
        self.assertContains(response, "غير محسومة أو متعارضة")
        self.assertContains(response, "دون إحالات مرجعية")

    def test_filters_survive_list_detail_next_previous_and_return_navigation(self):
        filters = {"q": "intake", "status": "blocked", "refs": "missing"}
        response = self.get(reverse("editorial_queue:index"), data=filters)
        rows = response.context["rows"]
        self.assertGreater(len(rows), 1)
        for index, row in enumerate(rows):
            parsed = urlsplit(row["url"])
            self.assertEqual(
                parse_qs(parsed.query), {key: [value] for key, value in filters.items()}
            )
            detail = self.get(row["url"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.context["selection"].position, index + 1)
            self.assertEqual(
                detail.context["previous_url"], rows[index - 1]["url"] if index else None
            )
            self.assertEqual(
                detail.context["next_url"],
                rows[index + 1]["url"] if index + 1 < len(rows) else None,
            )
            self.assertEqual(
                parse_qs(urlsplit(detail.context["return_url"]).query), parse_qs(parsed.query)
            )

    def test_direct_detail_outside_filter_is_explicit_and_does_not_infer_neighbors(self):
        response = self.get(reverse("editorial_queue:detail", args=["history"]) + "?status=blocked")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"].case.key, "history")
        self.assertIsNone(response.context["previous_url"])
        self.assertIsNone(response.context["next_url"])
        self.assertContains(response, "هذا السجل خارج التصفية الحالية")
        self.assertEqual(
            response.context["return_url"], reverse("editorial_queue:index") + "?status=blocked"
        )

    def test_history_links_select_exact_workbench_revision_and_all_fragments_resolve(self):
        response = self.get(reverse("editorial_queue:detail", args=["history"]))
        self.assertEqual(response.status_code, 200)
        base = reverse("editorial_workbench:detail", args=["history"])
        self.assertEqual(response.context["workbench_url"], base)
        self.assertEqual(
            [row["entry"].revision.number for row in response.context["history_rows"]],
            [1, 2, 4, 7, 9, 11],
        )
        parser = NavigationParser(response.content.decode())
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for link in parser.links:
            if link.startswith("#"):
                self.assertIn(link[1:], parser.ids)
        for row in response.context["history_rows"]:
            number = row["entry"].revision.number
            self.assertEqual(row["url"], base + f"?revision={number}#snapshot")
            workbench = self.get(row["url"])
            self.assertEqual(workbench.status_code, 200)
            self.assertEqual(workbench.context["selected_revision"].number, number)
            workbench_parser = NavigationParser(workbench.content.decode())
            self.assertIn(urlsplit(row["history_url"]).fragment, workbench_parser.ids)
            self.assertIn(f"audit-{number}", parser.ids)
        self.assertContains(response, base + "#intake")
        self.assertContains(response, base + "#references")
        self.assertContains(response, base + "#audit")

    def test_detail_provenance_shows_exact_hashes_and_correct_source_kind(self):
        for row in (build_queue()[0], build_queue()[1]):
            with self.subTest(key=row.case.key):
                response = self.get(reverse("editorial_queue:detail", args=[row.case.key]))
                self.assertContains(response, row.source_sha256)
                self.assertContains(response, row.case.payload_sha256)
                self.assertContains(response, row.case.fixture_label)
                if row.case.source_start is None:
                    self.assertContains(response, "لا توجد حدود في ملف أصلي")
                    self.assertContains(response, "هذه مؤشرات أحدث لقطة ثابتة")
                else:
                    self.assertContains(response, f"البداية {row.case.source_start}")
                    self.assertContains(response, f"النهاية غير المشمولة {row.case.source_end}")

    def test_no_draft_detail_does_not_borrow_revision_or_audit_history(self):
        response = self.get(reverse("editorial_queue:detail", args=["intake-2"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["history_rows"], ())
        self.assertIsNone(response.context["audit"])
        self.assertContains(response, "لا توجد مسودة أو مراجعات لهذا المدخل")
        self.assertContains(response, "لا توجد لقطات متاحة للتدقيق لهذا المدخل")
        self.assertNotContains(response, "?revision=")
        self.assertEqual(
            response.context["workbench_url"],
            reverse("editorial_workbench:detail", args=["intake-2"]),
        )

    def test_empty_result_and_empty_dataset_have_recovery(self):
        url = reverse("editorial_queue:index")
        response = self.get(url + "?q=not-in-fixed-fixtures")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], ())
        self.assertContains(response, "لا توجد سجلات تطابق البحث والتصفية")
        self.assertContains(response, f'href="{url}"')
        with patch.object(views, "build_queue_catalog", return_value=QueueCatalog((), ())):
            response = self.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 0)
        self.assertContains(response, "عرض جميع السجلات")

    def test_invalid_queries_fail_before_fixture_loading_on_list_and_detail(self):
        with patch.object(views, "build_queue_catalog") as build:
            for base in (
                reverse("editorial_queue:index"),
                reverse("editorial_queue:detail", args=["history"]),
            ):
                for suffix in (
                    "?q=a&q=b",
                    "?status=ready&status=review",
                    "?refs=missing&refs=verified",
                    "?status=approved",
                    "?refs=all",
                    "?revision=1",
                    "?file=C:/secret",
                    "?q=%00",
                    "?q=%7f",
                    "?q=%0a",
                    "?q=" + "a" * 81,
                ):
                    with self.subTest(base=base, suffix=suffix):
                        response = self.get(base + suffix)
                        self.assertEqual(response.status_code, 400)
                        self.assertContains(
                            response, "العودة إلى القائمة ومسح التصفية", status_code=400
                        )
            build.assert_not_called()

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2)
    def test_too_many_query_fields_has_helpful_error_without_loading(self):
        with patch.object(views, "build_queue_catalog") as build:
            response = self.get(
                reverse("editorial_queue:index") + "?q=a&status=ready&refs=verified"
            )
        self.assertEqual(response.status_code, 400)
        build.assert_not_called()

    def test_missing_case_and_expected_fixture_errors_have_safe_recovery(self):
        response = self.get(reverse("editorial_queue:detail", args=["no-such-key"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "السجل الاصطناعي غير موجود", status_code=404)
        for error in (WorkbenchDataError("internal-details"), HistoryDataError("internal-details")):
            with patch.object(views, "build_queue_catalog", side_effect=error):
                response = self.get(reverse("editorial_queue:index"))
            self.assertEqual(response.status_code, 503)
            self.assertContains(response, "تعذر تحميل قائمة العينات بأمان", status_code=503)
            self.assertNotContains(response, "internal-details", status_code=503)

    def test_existing_guard_blocks_remote_host_peer_and_production_for_every_route(self):
        urls = [
            reverse("editorial_queue:index"),
            reverse("editorial_queue:detail", args=["history"]),
            reverse("editorial_queue:style"),
        ]
        with patch.object(views, "build_queue_catalog") as build:
            for url in urls:
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "10.0.0.1"),
                    ("localhost", ""),
                ):
                    with self.subTest(url=url, host=host, peer=peer):
                        self.assertEqual(
                            self.client.get(url, HTTP_HOST=host, REMOTE_ADDR=peer).status_code, 404
                        )
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(url).status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(url).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(url).status_code, 404)
            build.assert_not_called()

    def test_ipv6_loopback_is_supported(self):
        response = self.client.get(
            reverse("editorial_queue:index"), HTTP_HOST="[::1]", REMOTE_ADDR="::1"
        )
        self.assertEqual(response.status_code, 200)

    def test_only_safe_methods_are_accepted_and_head_has_no_body(self):
        urls = [
            reverse("editorial_queue:index"),
            reverse("editorial_queue:detail", args=["history"]),
            reverse("editorial_queue:style"),
        ]
        for url in urls:
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(
                        url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    )
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
            response = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")

    def test_response_headers_and_fixture_content_are_safe(self):
        row = build_queue()[0]
        case = replace(
            row.case, question='<script>alert("x")</script>', raw_source="<svg onload=alert(1)>"
        )
        with patch.object(
            views, "build_queue_catalog", return_value=QueueCatalog((replace(row, case=case),), ())
        ):
            response = self.get(reverse("editorial_queue:detail", args=["history"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "&lt;svg")
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, 'href="https://example.invalid')
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_stylesheet_is_guarded_query_free_and_reports_missing_asset(self):
        url = reverse("editorial_queue:style")
        response = self.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response["Content-Type"])
        self.assertIn(b":focus-visible", response.content)
        self.assertEqual(self.get(url + "?file=other").status_code, 400)
        with patch.object(Path, "read_bytes", side_effect=OSError("private-path")):
            response = self.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private-path", status_code=503)
