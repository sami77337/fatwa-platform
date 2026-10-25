"""Connected desk, exact investigation targets, preserved text and access guards."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_followup.services import build_followup
from apps.editorial_workbench.services import WorkbenchDataError
from apps.revision_core.revision_history import HistoryDataError


class PageParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.links = []
        self.forms = []
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "form":
            self.forms.append(attrs)


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class FollowupViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_rtl_list_is_connected_filterable_and_read_only(self):
        response = self.get(reverse("editorial_followup:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 20)
        self.assertEqual(response.context["followup_total"], 17)
        self.assertEqual(len(response.context["rows"]), 17)
        for marker in (
            'lang="ar"',
            'dir="rtl"',
            'href="#main-content"',
            'for="reason"',
            'for="batch"',
            'for="status"',
            "Gate B NOT_PASSED",
            "C/D/E HOLD",
            "Phase01 BLOCKED",
            "SCOPE_DEVIATION_HOLD",
            "NOT_DEPLOYED",
        ):
            self.assertContains(response, marker)
        parsed = PageParser(response.content.decode())
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertTrue(all(form.get("method") == "get" for form in parsed.forms))
        self.assertNotIn("script", parsed.tags)

    def test_filters_survive_every_neighbor_and_return(self):
        filters = {"reason": "missing_receipt", "status": "blocked", "batch": "original"}
        response = self.get(reverse("editorial_followup:index"), data=filters)
        rows = response.context["rows"]
        self.assertGreater(len(rows), 1)
        for i, row in enumerate(rows):
            detail = self.get(row["url"])
            self.assertEqual(detail.context["selection"].position, i + 1)
            self.assertEqual(detail.context["previous_url"], rows[i - 1]["url"] if i else None)
            self.assertEqual(
                detail.context["next_url"], rows[i + 1]["url"] if i + 1 < len(rows) else None
            )
            self.assertEqual(
                parse_qs(urlsplit(detail.context["return_url"]).query),
                {key: [value] for key, value in filters.items()},
            )

    def test_every_detail_and_technical_link_targets_exact_record_and_anchor(self):
        catalog = build_followup()
        for item in catalog.rows:
            key = item.row.case.key
            response = self.get(reverse("editorial_followup:detail", args=[key]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["selected"].row.case.key, key)
            parsed = PageParser(response.content.decode())
            self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
            for name in ("workbench_url", "investigation_url"):
                target = response.context[name]
                self.assertIn(key, target)
                self.assertNotIn("?", target)
                self.assertEqual(self.get(target).status_code, 200)
            for entry in response.context["reference_rows"]:
                url = entry["url"]
                self.assertIn(url, parsed.links)
                target = self.get(url)
                self.assertEqual(target.status_code, 200)
                self.assertIn(
                    f"reference-{entry['ref']['reference_ordinal']}",
                    PageParser(target.content.decode()).ids,
                )
            receipt_url = response.context["receipt_url"]
            if item.row.case.record is None:
                self.assertIsNone(receipt_url)
            else:
                self.assertIn(receipt_url, parsed.links)
                self.assertEqual(
                    parse_qs(urlsplit(receipt_url).query),
                    {"revision": [str(item.row.case.record.current.number)]},
                )
                self.assertEqual(self.get(receipt_url).status_code, 200)

    def test_malformed_batch_and_empty_filtered_results_are_explicit(self):
        response = self.get(
            reverse("editorial_followup:index"), data={"batch": "synthetic-malformed"}
        )
        self.assertEqual(response.context["rows"], ())
        self.assertContains(response, "MALFORMED_INPUT")
        self.assertContains(response, build_followup().batches[-1].source.input_sha256)
        response = self.get(
            reverse("editorial_followup:index"),
            data={"status": "ready", "reason": "missing_receipt"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], ())

    def test_outside_filter_details_do_not_get_neighbors_or_fallbacks(self):
        for key in ("history", "intake-7"):
            response = self.get(
                reverse("editorial_followup:detail", args=[key]), data={"reason": "missing_receipt"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context["selection"].position)
            self.assertIsNone(response.context["previous_url"])
            self.assertIsNone(response.context["next_url"])
            self.assertContains(response, "خارج")
        self.assertEqual(
            self.get(reverse("editorial_followup:detail", args=["not-a-case"])).status_code, 404
        )

    def test_invalid_queries_fail_before_building_catalog(self):
        for query in (
            "reason=unknown",
            "status=approved",
            "batch=../secret",
            "batch=" + "x" * 101,
            "reason=missing_receipt&reason=missing_receipt",
            "path=secret",
            "status=%00",
            "&".join(f"x{i}=y" for i in range(17)),
        ):
            with patch("apps.editorial_followup.views.build_followup") as build:
                response = self.get(reverse("editorial_followup:index") + "?" + query)
                self.assertEqual(response.status_code, 400, query)
                build.assert_not_called()
        self.assertEqual(
            self.get(reverse("editorial_followup:index") + "?batch=unknown").status_code, 400
        )

    def test_expected_data_failures_are_safe_and_not_false_empty_success(self):
        for error in (WorkbenchDataError, HistoryDataError):
            with patch(
                "apps.editorial_followup.views.build_followup", side_effect=error("internal-secret")
            ):
                response = self.get(reverse("editorial_followup:index"))
            self.assertEqual(response.status_code, 503)
            self.assertNotContains(response, "internal-secret", status_code=503)
            self.assertEqual(response["Cache-Control"], "no-store")

    def test_exact_source_and_question_escape_markup_preserving_crlf(self):
        catalog = build_followup()
        item = catalog.rows[0]
        text = '\n  سُؤَالٌ e\u0301\r\n<script>alert(1)</script> & "نص"  '
        changed = replace(
            item, row=replace(item.row, case=replace(item.row.case, question=text, raw_source=text))
        )
        with patch(
            "apps.editorial_followup.views.build_followup",
            return_value=replace(catalog, rows=(changed,)),
        ):
            response = self.get(reverse("editorial_followup:detail", args=[item.row.case.key]))
        self.assertNotContains(response, "<script>")
        self.assertContains(response, "&#13;")
        self.assertContains(response, "&lt;script&gt;")

        class CodeText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.depth = 0
                self.chunks = []

            def handle_starttag(self, tag, attrs):
                if tag == "code":
                    self.depth += 1

            def handle_endtag(self, tag):
                if tag == "code":
                    self.depth -= 1

            def handle_data(self, data):
                if self.depth:
                    self.chunks.append(data)

        parser = CodeText()
        parser.feed(response.content.decode())
        self.assertIn(text, parser.chunks)

    def test_guards_run_before_data_loading_and_writes_are_rejected(self):
        urls = [
            reverse("editorial_followup:index"),
            reverse("editorial_followup:detail", args=["history"]),
            reverse("editorial_followup:style"),
        ]
        for url in urls:
            with patch("apps.editorial_followup.views.build_followup") as build:
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "192.0.2.1"),
                    ("localhost", ""),
                ):
                    self.assertEqual(
                        self.client.get(url, HTTP_HOST=host, REMOTE_ADDR=peer).status_code, 404
                    )
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(url).status_code, 404)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(url).status_code, 404)
                for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
                    self.assertEqual(
                        self.client.generic(
                            method, url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                        ).status_code,
                        405,
                    )
                build.assert_not_called()
            response = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_stylesheet_is_guarded_local_and_rejects_extra_arguments(self):
        response = self.get(reverse("editorial_followup:style"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response["Content-Type"])
        self.assertContains(response, ":focus-visible")
        self.assertContains(response, "@media")
        self.assertEqual(
            self.get(reverse("editorial_followup:style") + "?path=secret").status_code, 400
        )
