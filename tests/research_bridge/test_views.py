"""HTTP boundaries and read-only reference navigation over synthetic fixtures."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_workbench.services import WorkbenchDataError
from apps.reference_links import CatalogReadError, Heading, SnapshotCatalog
from apps.reference_triage.services import build_investigation


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids, self.links, self.tags, self.text = [], [], [], []
        self.feed(html.replace("\r\n", "\n").replace("\r", "\n"))

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
class ResearchBridgeViewsTests(SimpleTestCase):
    def setUp(self):
        # The live DB is deliberately unavailable; views must still recover safely.
        self.catalog = patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            side_effect=CatalogReadError("private-db-host"),
        ).start()
        self.addCleanup(patch.stopall)

    def get(self, path, **extra):
        return self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_index_lists_twenty_fixed_cases_without_catalog_access(self):
        response = self.get("/dev/research-bridge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 20)
        self.assertContains(response, "/dev/research-bridge/history")
        self.catalog.assert_not_called()

    def routes(self):
        return ("/dev/research-bridge", "/dev/research-bridge/history")

    def test_all_cases_have_stable_back_links_neighbors_and_reference_anchors(self):
        rows = self.get(self.routes()[0]).context["rows"]
        for index, row in enumerate(rows):
            key = row["row"].case.key
            with self.subTest(key=key):
                response = self.get(row["url"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["selected"].case.key, key)
                self.assertEqual(
                    response.context["previous_url"], rows[index - 1]["url"] if index else None
                )
                self.assertEqual(
                    response.context["next_url"],
                    rows[index + 1]["url"] if index + 1 < len(rows) else None,
                )
                self.assertContains(response, reverse("reference_triage:detail", args=[key]))
                self.assertContains(response, reverse("editorial_workbench:detail", args=[key]))
                self.assertContains(response, row["row"].case.payload_sha256)
                self.assertContains(response, row["row"].case.fixture_label)
                document = Document(response.content.decode())
                self.assertEqual(len(document.ids), len(set(document.ids)))
                for ref in row["row"].references:
                    self.assertIn(f"reference-{ref.ordinal}", document.ids)
                for href in document.links:
                    if href.startswith("#"):
                        self.assertIn(href[1:], document.ids)
                    self.assertFalse(href.startswith(("http:", "https:", "javascript:")))
                self.assertNotIn("form", document.tags)

    def test_live_matching_catalog_shows_path_location_and_native_catalog_link(self):
        root = "كِتَابٌ اصطناعي"
        catalog = SnapshotCatalog(
            tuple(
                Heading(
                    7001,
                    row,
                    "مرجع اصطناعي لتجارب Wave7",
                    title,
                    "الأول",
                    page,
                    (root,) if row == 1 else (root, title),
                    "wave7-synthetic-toc",
                    "622",
                    "b" * 64,
                    "wave7-synthetic-edition-v1",
                    "a" * 64,
                )
                for row, title, page in (
                    (1, root, 7),
                    (2, "بابٌ اصطناعي أول", 8),
                    (3, "بابٌ اصطناعي ثان", 9),
                )
            )
        )
        self.catalog.side_effect = catalog.lookup
        report = build_investigation()
        selected = next(
            row for row in report.cases if any(ref.status == "verified" for ref in row.references)
        )
        response = self.get(reverse("research_bridge:detail", args=[selected.case.key]))
        self.assertEqual(response.status_code, 200)
        entries = response.context["references"]
        verified = [entry for entry in entries if entry["result"].status == "verified"]
        self.assertTrue(verified)
        for entry in verified:
            evidence = entry["result"].evidence
            self.assertContains(response, evidence.work_title)
            self.assertContains(response, evidence.heading_title)
            for title in evidence.path:
                self.assertContains(response, title)
            self.assertIn(
                f"الجزء: {evidence.printed_part}", "".join(Document(response.content.decode()).text)
            )
            self.assertContains(response, f"الصفحة: {evidence.printed_page}")
            self.assertIn(entry["result"].catalog_url, Document(response.content.decode()).links)

    def test_unavailable_catalog_closes_each_link_with_recovery_and_no_internal_error(self):
        report = build_investigation()
        selected = next(
            row for row in report.cases if any(ref.status == "verified" for ref in row.references)
        )
        response = self.get(reverse("research_bridge:detail", args=[selected.case.key]))
        self.assertEqual(response.status_code, 200)
        for entry in response.context["references"]:
            self.assertEqual(entry["result"].status, "unverified")
            self.assertIsNone(entry["result"].catalog_url)
            self.assertContains(response, entry["result"].recovery)
        self.assertNotContains(response, "private-db-host")
        self.assertFalse(
            any(
                href.startswith("/fiqh/nodes/")
                for href in Document(response.content.decode()).links
            )
        )

    def test_reference_text_identity_and_question_keep_exact_unicode_and_escape_markup(self):
        report = build_investigation()
        row = report.cases[0]
        payload = '\n<script>alert("x")</script>\r\n  سُؤَالٌ e\u0301'
        ref = replace(row.references[0], source_text=payload, original_identity=payload)
        row = replace(row, case=replace(row.case, question=payload), references=(ref,))
        with patch(
            "apps.research_bridge.views.build_investigation",
            return_value=replace(report, cases=(row,)),
        ):
            response = self.get(reverse("research_bridge:detail", args=[row.case.key]))
        document = Document(response.content.decode())
        self.assertNotIn("script", document.tags)
        self.assertNotIn("iframe", document.tags)
        self.assertGreaterEqual("".join(document.text).count(payload), 3)

    def test_any_query_identity_or_filter_is_rejected_before_sources_load(self):
        with patch("apps.research_bridge.views.build_investigation") as build:
            for route in self.routes():
                for suffix in (
                    "?edition=7001",
                    "?edition_id=7001",
                    "?source_row_id=2",
                    "?file=C:/private",
                    "?status=verified",
                    "?x=",
                    "?x=1&x=2",
                    "?verified_identity=%7B%7D",
                    "?catalog_url=https://invalid.example",
                ):
                    with self.subTest(route=route, suffix=suffix):
                        response = self.get(route + suffix)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response["Cache-Control"], "no-store")
            build.assert_not_called()
            self.catalog.assert_not_called()

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
    def test_excess_query_fields_fail_closed(self):
        response = self.get(self.routes()[0] + "?x=1&y=2")
        self.assertEqual(response.status_code, 400)

    def test_unknown_key_and_invalid_source_return_nonleaking_recovery(self):
        response = self.get("/dev/research-bridge/missing-key")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "/dev/research-bridge", status_code=404)
        with patch(
            "apps.research_bridge.views.build_investigation",
            side_effect=WorkbenchDataError("private-path-secret"),
        ):
            for route in self.routes():
                response = self.get(route)
                self.assertEqual(response.status_code, 503)
                self.assertNotContains(response, "private-path-secret", status_code=503)
                self.assertContains(response, "/dev/research-bridge", status_code=503)
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_remote_and_production_requests_block_before_loading(self):
        with patch("apps.research_bridge.views.build_investigation") as build:
            for route in self.routes():
                for host, peer in (
                    ("remote.invalid", "127.0.0.1"),
                    ("localhost", "10.0.0.1"),
                    ("localhost", ""),
                ):
                    response = self.client.get(
                        route,
                        HTTP_HOST=host,
                        REMOTE_ADDR=peer,
                        HTTP_X_FORWARDED_FOR="127.0.0.1",
                        HTTP_X_FORWARDED_HOST="localhost",
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertNotIn(b"source_input_sha256", response.content)
                with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                    self.assertEqual(self.get(route).status_code, 404)
                with override_settings(FATWA_PRODUCTION=True):
                    self.assertEqual(self.get(route).status_code, 404)
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(route).status_code, 404)
            build.assert_not_called()
            self.catalog.assert_not_called()

    def test_get_head_only_and_ipv6_loopback(self):
        for route in self.routes():
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                with patch("apps.research_bridge.views.build_investigation") as build:
                    response = getattr(self.client, method)(
                        route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    )
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Allow"], "GET, HEAD")
                self.assertEqual(response["Cache-Control"], "no-store")
                build.assert_not_called()
            response = self.client.head(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
        response = self.client.get(self.routes()[0], HTTP_HOST="[::1]", REMOTE_ADDR="::1")
        self.assertEqual(response.status_code, 200)

    def test_rtl_accessibility_security_headers_and_technical_limits(self):
        for route in self.routes():
            response = self.get(route)
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'none'", response["Content-Security-Policy"])
            for text in (
                'lang="ar"',
                'dir="rtl"',
                'href="#main-content"',
                "اصطناعي",
                "علمية",
                "أرشيف",
                "NOT_DEPLOYED",
                "Gate B NOT_PASSED",
                "C/D/E HOLD",
                "Phase01 BLOCKED",
                "SCOPE_DEVIATION_HOLD",
            ):
                self.assertContains(response, text)
