"""Dashboard contracts over FAST3's actual fixed synthetic services; no database."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase, override_settings


class Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.ids = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if "id" in attrs:
            self.ids.append(attrs["id"])


@override_settings(ALLOWED_HOSTS=["localhost", "[::1]", "remote.invalid"])
class DashboardTests(SimpleTestCase):
    url = "/dev/editorial-dashboard"

    def get(self, url=None, **kwargs):
        return self.client.get(
            url or self.url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **kwargs
        )

    def test_dashboard_counts_real_rows_without_inventing_preparation_or_approval(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        report = response.context["dashboard"]
        self.assertEqual(
            (report.total_rows, report.questions, report.prepared_records), (20, 17, 6)
        )
        self.assertEqual([item["count"] for item in report.statuses], [4, 4, 12])
        self.assertEqual([item["count"] for item in report.references], [8, 7, 0, 8])
        self.assertEqual(report.reference_total, 15)
        self.assertEqual(report.attention_count, 17)
        self.assertEqual([item["count"] for item in report.source_diagnostics], [1, 3, 0])
        self.assertEqual(len(report.rows), 20)
        self.assertEqual(len(report.batches), 5)
        self.assertEqual(report.batches[-1]["batch"].source.error_code, "MALFORMED_INPUT")
        self.assertEqual(report.batches[-1]["batch"].total, 0)
        self.assertContains(response, "NOT_DEPLOYED")
        self.assertContains(response, "SCOPE_DEVIATION_HOLD")

    def test_batch_filter_reconciles_metrics_and_retains_exact_diagnostic_identity(self):
        response = self.get(data={"batch": "synthetic-json"})
        self.assertEqual(response.status_code, 200)
        report = response.context["dashboard"]
        self.assertEqual((report.total_rows, report.questions, report.prepared_records), (4, 3, 1))
        self.assertEqual([item["count"] for item in report.statuses], [0, 1, 3])
        self.assertEqual([item["count"] for item in report.source_diagnostics], [1, 2, 0])
        missing = [
            item
            for item in report.rows
            if any(issue["code"] == "missing_source" for issue in item["diagnostics"])
        ]
        self.assertEqual([item["row"].case.key for item in missing], ["batch-synthetic-json-2"])
        self.assertEqual(missing[0]["row"].case.external_id, "SYN-JSON-2")
        self.assertEqual(len(report.batches), 5)

    def test_metric_links_open_matching_queue_and_investigation_counts(self):
        for batch in ("", "original", "synthetic-json", "synthetic-malformed"):
            response = self.get(data={"batch": batch})
            self.assertEqual(response.status_code, 200)
            report = response.context["dashboard"]
            for metric in report.statuses:
                target = self.get(metric["url"])
                self.assertEqual(target.status_code, 200)
                self.assertEqual(len(target.context["rows"]), metric["count"])
            for metric in report.references:
                # Original queue grouping has two investigation groups; links must not
                # misrepresent a group count as the global investigation count.
                if metric["url"]:
                    target = self.get(metric["url"])
                    self.assertEqual(target.status_code, 200)
                    self.assertEqual(
                        getattr(target.context["filtered_summary"], metric["code"]),
                        metric["count"],
                    )

    def test_all_case_links_select_same_key_including_duplicates_and_rejected_rows(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for item in response.context["dashboard"].rows:
            key = item["row"].case.key
            with self.subTest(key=key):
                queue = self.get(item["queue_url"])
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(queue.context["selected"].case.key, key)
                workbench = self.get(item["workbench_url"])
                self.assertEqual(workbench.status_code, 200)
                self.assertEqual(workbench.context["case"].key, key)
                investigation = self.get(item["investigation_url"])
                self.assertEqual(investigation.status_code, 200)
                self.assertEqual(investigation.context["selected"].case.key, key)
                packet = self.get(item["packet_url"])
                self.assertEqual(packet.status_code, 200)
                self.assertEqual(packet.context["packet"]["identity"]["case_key"], key)

    def test_invalid_filter_is_rejected_before_loading_and_error_is_recoverable(self):
        from apps.editorial_dashboard import views

        with patch.object(views, "build_dashboard") as build:
            for suffix in (
                "?batch=a&batch=b",
                "?file=C:/private",
                "?batch=../a",
                "?batch=" + "x" * 101,
            ):
                response = self.get(self.url + suffix)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, self.url, status_code=400)
            build.assert_not_called()
        self.assertEqual(self.get(data={"batch": "unknown"}).status_code, 400)

    def test_guard_and_safe_methods_cover_dashboard_and_stylesheet(self):
        from apps.editorial_dashboard import views

        with patch.object(views, "build_dashboard") as build:
            for url in (self.url, self.url + "/style.css"):
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "10.0.0.1"),
                    ("localhost", ""),
                ):
                    response = self.client.get(url, HTTP_HOST=host, REMOTE_ADDR=peer)
                    self.assertEqual(response.status_code, 404)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(url).status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(url).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(url).status_code, 404)
                for method in ("post", "put", "patch", "delete", "options", "trace"):
                    response = getattr(self.client, method)(url, HTTP_HOST="localhost")
                    self.assertEqual(response.status_code, 405)
                build.assert_not_called()

    def test_headers_head_and_accessible_local_navigation(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])
        for marker in ('lang="ar"', 'dir="rtl"', 'href="#main-content"', 'for="batch"'):
            self.assertContains(response, marker)
        parser = Links(response.content.decode())
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for link in parser.links:
            self.assertFalse(urlsplit(link).netloc)
            if link.startswith("#"):
                self.assertIn(link[1:], parser.ids)
        for url in (self.url, self.url + "/style.css"):
            response = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
        self.assertEqual(self.get(self.url + "/style.css?file=x").status_code, 400)

    def test_service_failure_does_not_publish_partial_or_private_diagnostics(self):
        from apps.editorial_dashboard import views
        from apps.editorial_workbench.services import WorkbenchDataError

        with patch.object(views, "build_dashboard", side_effect=WorkbenchDataError("private-path")):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private-path", status_code=503)
        self.assertContains(response, self.url, status_code=503)

    def test_empty_and_malformed_batches_never_invent_records(self):
        response = self.get(data={"batch": "synthetic-malformed"})
        self.assertEqual(response.status_code, 200)
        report = response.context["dashboard"]
        self.assertEqual((report.total_rows, report.questions, report.prepared_records), (0, 0, 0))
        self.assertEqual(report.rows, ())
        self.assertContains(response, "MALFORMED_INPUT")
        from apps.editorial_dashboard import services
        from apps.editorial_queue.services import QueueCatalog
        from apps.reference_triage.services import Investigation, Summary

        empty_diagnostics = replace(
            services.diagnose_batches((), synthetic_fixtures_only=True),
        )
        with (
            patch.object(services, "build_queue_catalog", return_value=QueueCatalog((), ())),
            patch.object(
                services,
                "build_investigation",
                return_value=Investigation((), (), Summary(0, 0, 0, 0, 0, 0)),
            ),
            patch.object(services, "diagnose_batches", return_value=empty_diagnostics),
        ):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"].total_rows, 0)

    def test_changed_source_identity_fails_closed_instead_of_mixing_diagnostics(self):
        from apps.editorial_dashboard import services

        catalog = services.build_queue_catalog()
        changed = replace(
            catalog.rows[-1], case=replace(catalog.rows[-1].case, payload_sha256="0" * 64)
        )
        with patch.object(
            services,
            "build_queue_catalog",
            return_value=replace(catalog, rows=(*catalog.rows[:-1], changed)),
        ):
            response = self.get()
        self.assertEqual(response.status_code, 503)

    def test_exact_source_is_escaped_without_normalization_or_crlf_loss(self):
        from apps.editorial_dashboard import services

        catalog = services.build_queue_catalog()
        investigation = services.build_investigation()
        question = '\n  <script>alert("x")</script>\r\nسُؤال e\u0301  '
        changed = replace(catalog.rows[0].case, question=question)
        catalog = replace(catalog, rows=(replace(catalog.rows[0], case=changed), *catalog.rows[1:]))
        investigation = replace(
            investigation,
            cases=(replace(investigation.cases[0], case=changed), *investigation.cases[1:]),
        )
        with (
            patch.object(services, "build_queue_catalog", return_value=catalog),
            patch.object(services, "build_investigation", return_value=investigation),
        ):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertContains(response, "&#13;\nسُؤال e\u0301  ")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
    def test_too_many_query_fields_fail_before_loading(self):
        from apps.editorial_dashboard import views

        with patch.object(views, "build_dashboard") as build:
            response = self.get(self.url + "?batch=a&extra=b")
        self.assertEqual(response.status_code, 400)
        build.assert_not_called()

    def test_ipv6_loopback_and_missing_stylesheet(self):
        from pathlib import Path

        response = self.client.get(self.url, HTTP_HOST="[::1]", REMOTE_ADDR="::1")
        self.assertEqual(response.status_code, 200)
        with patch.object(Path, "read_bytes", side_effect=OSError("private-path")):
            response = self.get(self.url + "/style.css")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private-path", status_code=503)
