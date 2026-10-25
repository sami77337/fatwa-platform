"""Connected synthetic investigation HTTP and access-boundary regressions."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_workbench.services import (
    WorkbenchDataError,
    build_cases,
    build_prepared_workbench,
)


class NavigationParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.links = []
        self.text = []
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])

    def handle_data(self, data):
        self.text.append(data)


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class ReferenceTriageViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def routes(self):
        return (
            reverse("reference_triage:index"),
            reverse("reference_triage:detail", args=["history"]),
        )

    def test_index_connects_every_existing_case_and_includes_failed_batch(self):
        response = self.get(reverse("reference_triage:index"))
        self.assertEqual(response.status_code, 200)
        expected = build_cases() + build_prepared_workbench().cases
        rows = response.context["rows"]
        self.assertEqual([row["row"].case.key for row in rows], [case.key for case in expected])
        for row in rows:
            self.assertContains(response, row["url"])
            self.assertContains(response, row["workbench_url"])
        self.assertContains(response, "synthetic-malformed")
        for marker in (
            'lang="ar"',
            'dir="rtl"',
            'href="#main-content"',
            'for="status"',
            'for="batch"',
            "NOT_DEPLOYED",
            "Gate B NOT_PASSED",
            "C/D/E HOLD",
            "Phase01 BLOCKED",
            "SCOPE_DEVIATION_HOLD",
        ):
            self.assertContains(response, marker)

    def test_filters_keep_record_occurrences_and_preserve_navigation_context(self):
        filters = {"status": "verified", "batch": "wave7"}
        response = self.get(reverse("reference_triage:index"), data=filters)
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertGreater(len(rows), 0)
        for index, row in enumerate(rows):
            self.assertEqual(row["row"].batch_id, "wave7")
            parsed = urlsplit(row["url"])
            self.assertEqual(
                parse_qs(parsed.query), {key: [value] for key, value in filters.items()}
            )
            detail = self.get(row["url"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.context["selected"].case.key, row["row"].case.key)
            self.assertEqual(
                parse_qs(urlsplit(detail.context["return_url"]).query), parse_qs(parsed.query)
            )
            self.assertEqual(
                detail.context["previous_url"], rows[index - 1]["url"] if index else None
            )
            self.assertEqual(
                detail.context["next_url"],
                rows[index + 1]["url"] if index + 1 < len(rows) else None,
            )

    def test_each_detail_returns_to_exact_workbench_case_with_provenance(self):
        for case in build_cases() + build_prepared_workbench().cases:
            with self.subTest(case=case.key):
                response = self.get(reverse("reference_triage:detail", args=[case.key]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["selected"].case.key, case.key)
                self.assertContains(response, case.payload_sha256)
                self.assertContains(response, case.fixture_label)
                self.assertContains(
                    response, reverse("editorial_workbench:detail", args=[case.key])
                )
                parser = NavigationParser(response.content.decode())
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                for link in parser.links:
                    if link.startswith("#"):
                        self.assertIn(link[1:], parser.ids)
                    self.assertFalse(link.startswith("https://example.invalid"))
                workbench_links = [
                    link
                    for link in parser.links
                    if urlsplit(link).path == reverse("editorial_workbench:detail", args=[case.key])
                ]
                self.assertTrue(workbench_links)
                workbench = self.get(workbench_links[0])
                self.assertEqual(workbench.status_code, 200)
                self.assertEqual(workbench.context["case"].key, case.key)
                target = urlsplit(workbench_links[0]).fragment
                if target:
                    self.assertIn(target, NavigationParser(workbench.content.decode()).ids)
                self.assertNotContains(response, '<form method="post"')

    def test_verified_mismatched_and_missing_filters_are_distinct(self):
        url = reverse("reference_triage:index")
        for status in ("verified", "mismatched", "missing"):
            with self.subTest(status=status):
                response = self.get(url, data={"status": status})
                self.assertEqual(response.status_code, 200)
                rows = response.context["rows"]
                if status == "mismatched":
                    self.assertEqual(rows, ())
                else:
                    self.assertGreater(len(rows), 0)
                for row in rows:
                    refs = row["row"].case.references
                    if status == "missing":
                        self.assertEqual(refs, ())
                    elif status == "verified":
                        self.assertTrue(any(ref["status"] == "verified" for ref in refs))
                    else:
                        self.assertTrue(
                            any(
                                ref["status"] in {"mismatched", "mismatched_metadata"}
                                for ref in refs
                            )
                        )

    def test_mismatch_from_diagnostic_service_is_presented_without_promotion(self):
        from apps.reference_triage.services import build_investigation

        report = build_investigation()
        row = report.cases[0]
        mismatch = replace(
            row.references[0],
            status="mismatched",
            raw_status="mismatched_metadata",
            label="متعارض تقنيًا",
            reasons=("catalog_metadata_mismatch",),
            verified_identity="{}",
            evidence="null",
        )
        row = replace(row, references=(mismatch,))
        with patch(
            "apps.reference_triage.views.build_investigation",
            return_value=replace(report, cases=(row,)),
        ):
            response = self.get(reverse("reference_triage:index") + "?status=mismatched")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [entry["row"].case.key for entry in response.context["rows"]], [row.case.key]
            )
            detail = self.get(reverse("reference_triage:detail", args=[row.case.key]))
        self.assertContains(detail, "mismatched_metadata")
        self.assertContains(detail, "catalog_metadata_mismatch")
        self.assertContains(detail, "متعارض تقنيًا")

    def test_exact_arabic_crlf_and_leading_whitespace_survive_html_parsing(self):
        case = next(
            case for case in build_prepared_workbench().cases if case.key == "batch-synthetic-csv-1"
        )
        response = self.get(reverse("reference_triage:detail", args=[case.key]))
        self.assertEqual(response.status_code, 200)
        # HTML normalizes literal CR/CRLF before parsing character references.
        html = response.content.decode().replace("\r\n", "\n").replace("\r", "\n")
        parsed = NavigationParser(html)
        self.assertIn(case.question, "".join(parsed.text))

    def test_technical_identity_source_and_question_are_escaped_without_remote_links(self):
        from apps.reference_triage.services import build_investigation

        report = build_investigation()
        row = report.cases[0]
        payload = '\n<script>alert("x")</script>\r\nسُؤَالٌ e\u0301'
        ref = replace(
            row.references[0],
            original_identity=payload,
            verified_identity=payload,
            evidence=payload,
            source_text=payload,
        )
        row = replace(
            row, case=replace(row.case, question=payload, raw_source=payload), references=(ref,)
        )
        with patch(
            "apps.reference_triage.views.build_investigation",
            return_value=replace(report, cases=(row,)),
        ):
            response = self.get(reverse("reference_triage:detail", args=[row.case.key]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        parsed = NavigationParser(
            response.content.decode().replace("\r\n", "\n").replace("\r", "\n")
        )
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("iframe", parsed.tags)
        self.assertIn(payload, "".join(parsed.text))
        self.assertGreaterEqual("".join(parsed.text).count('<script>alert("x")</script>'), 6)

    def test_detail_outside_filter_remains_explicit_without_neighbor_invention(self):
        response = self.get(reverse("reference_triage:detail", args=["history"]) + "?batch=wave7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"].case.key, "history")
        self.assertIsNone(response.context["previous_url"])
        self.assertIsNone(response.context["next_url"])
        self.assertContains(response, "خارج التصفية الحالية")
        self.assertEqual(
            response.context["return_url"], reverse("reference_triage:index") + "?batch=wave7"
        )

    def test_empty_filtered_results_provide_reset_and_failed_batch_does_not_invent_rows(self):
        url = reverse("reference_triage:index")
        response = self.get(url + "?batch=synthetic-malformed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], ())
        self.assertContains(response, f'href="{url}"')
        self.assertContains(response, "synthetic-malformed")

    def test_invalid_queries_fail_before_loading_fixed_sources(self):
        with patch("apps.reference_triage.views.build_investigation") as build:
            for base in self.routes():
                for suffix in (
                    "?status=verified&status=unresolved",
                    "?batch=wave7&batch=wave7",
                    "?status=approved",
                    "?file=C:/secret",
                    "?edition_id=7001",
                    "?source_row_id=2",
                    "?batch=%00",
                    "?batch=%0a",
                    "?batch=%7f",
                    "?batch=" + "a" * 101,
                ):
                    with self.subTest(base=base, suffix=suffix):
                        response = self.get(base + suffix)
                        self.assertEqual(response.status_code, 400)
                        self.assertContains(
                            response, reverse("reference_triage:index"), status_code=400
                        )
            build.assert_not_called()

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
    def test_excess_query_fields_fail_without_loading(self):
        with patch("apps.reference_triage.views.build_investigation") as build:
            response = self.get(reverse("reference_triage:index") + "?batch=wave7&status=verified")
        self.assertEqual(response.status_code, 400)
        build.assert_not_called()

    def test_unknown_selection_and_source_failure_have_nonleaking_recovery(self):
        response = self.get(reverse("reference_triage:detail", args=["no-such-key"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, reverse("reference_triage:index"), status_code=404)
        self.assertEqual(
            self.get(reverse("reference_triage:index") + "?batch=no-such-batch").status_code, 400
        )
        with patch(
            "apps.reference_triage.views.build_investigation",
            side_effect=WorkbenchDataError("private-path-secret"),
        ):
            for route in self.routes():
                response = self.get(route)
                self.assertEqual(response.status_code, 503)
                self.assertContains(response, reverse("reference_triage:index"), status_code=503)
                self.assertNotContains(response, "private-path-secret", status_code=503)
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_guards_block_remote_forwarded_and_production_requests_before_loading(self):
        with patch("apps.reference_triage.views.build_investigation") as build:
            for route in self.routes():
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "10.0.0.1"),
                    ("localhost", ""),
                ):
                    with self.subTest(route=route, host=host, peer=peer):
                        response = self.client.get(
                            route,
                            HTTP_HOST=host,
                            REMOTE_ADDR=peer,
                            HTTP_X_FORWARDED_FOR="127.0.0.1",
                            HTTP_X_FORWARDED_HOST="localhost",
                        )
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn(b"edition_id", response.content)
                        self.assertNotIn(b"source_input_sha256", response.content)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(route).status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(route).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(route).status_code, 404)
            build.assert_not_called()

    def test_ipv6_loopback_works(self):
        response = self.client.get(
            reverse("reference_triage:index"), HTTP_HOST="[::1]", REMOTE_ADDR="::1"
        )
        self.assertEqual(response.status_code, 200)

    def test_safe_methods_only_and_head_body_empty(self):
        for route in self.routes():
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                with self.subTest(route=route, method=method):
                    with patch("apps.reference_triage.views.build_investigation") as build:
                        response = getattr(self.client, method)(
                            route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                        )
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
                    build.assert_not_called()
            response = self.client.head(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")

    def test_success_headers_and_explicit_technical_verification_limits(self):
        for route in self.routes():
            response = self.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'none'", response["Content-Security-Policy"])
            self.assertContains(response, "اصطناعي")
            self.assertContains(response, "علمية")
            self.assertContains(response, "أرشيف")
