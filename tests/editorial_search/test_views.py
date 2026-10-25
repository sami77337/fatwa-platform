"""Real catalog HTTP search, exact revision navigation and local read-only guards."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_queue.services import QueueCatalog, build_queue_catalog
from apps.editorial_workbench.services import WorkbenchDataError
from apps.revision_core.revision_history import HistoryDataError


class SearchMarkup(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.labels = []
        self.text = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "label":
            self.labels.append(attrs.get("for"))

    def handle_data(self, data):
        self.text.append(data)


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "[::1]", "remote.invalid"])
class SearchViewTests(SimpleTestCase):
    def get(self, url=None, **extra):
        return self.client.get(
            url or reverse("editorial_search:index"),
            HTTP_HOST="localhost",
            REMOTE_ADDR="127.0.0.1",
            **extra,
        )

    def test_empty_search_is_rtl_labeled_and_does_not_list_everything(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"].total, 0)
        self.assertEqual(len(response.context["rows"]), 0)
        self.assertContains(response, 'lang="ar"')
        self.assertContains(response, 'dir="rtl"')
        markup = SearchMarkup(response.content.decode())
        self.assertTrue({"q", "source", "batch"}.issubset(markup.labels))
        self.assertContains(response, "NOT_DEPLOYED")

    def test_draft_results_link_each_exact_existing_revision(self):
        response = self.get(data={"q": "منقح", "source": "draft"})
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual([row["hit"].revision for row in rows], [2, 4, 7, 9, 11])
        for row in rows:
            parts = urlsplit(row["url"])
            self.assertEqual(parts.fragment, "snapshot")
            self.assertEqual(parse_qs(parts.query)["revision"], [str(row["hit"].revision)])
            detail = self.get(row["url"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.context["case"].key, row["hit"].case_key)
            self.assertEqual(detail.context["selected_revision"].number, row["hit"].revision)
        question = self.get(data={"q": "منقح", "source": "question"})
        self.assertEqual(question.context["result"].total, 0)

    def test_reference_matches_keep_historical_occurrence_identity(self):
        response = self.get(data={"q": "SYN-REMOVE", "source": "reference"})
        self.assertEqual(response.status_code, 200)
        rows = [row for row in response.context["rows"] if row["hit"].revision is not None]
        self.assertEqual({row["hit"].revision for row in rows}, {1, 9, 11})
        for row in rows:
            detail = self.get(row["url"])
            self.assertEqual(detail.status_code, 200)
            revision = detail.context["selected_revision"]
            self.assertEqual(revision.number, row["hit"].revision)
            self.assertIn("SYN-REMOVE", [ref.source_id for ref in revision.reference_links])

    def test_prepared_batch_filter_and_rejected_record_link(self):
        response = self.get(data={"q": "اصطناعي", "source": "question", "batch": "synthetic-csv"})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["result"].total, 0)
        self.assertTrue(
            all(row["hit"].batch_id == "synthetic-csv" for row in response.context["rows"])
        )
        rejected = self.get(data={"q": "intake-2", "source": "record"})
        row = rejected.context["rows"][0]
        self.assertIsNone(row["hit"].revision)
        self.assertNotIn("revision", parse_qs(urlsplit(row["url"]).query))
        self.assertEqual(self.get(row["url"]).context["case"].key, "intake-2")

    def test_pagination_preserves_search_and_filters_without_overlap(self):
        from apps.editorial_search import views

        catalog = build_queue_catalog()
        row = catalog.rows[0]
        catalog = QueueCatalog(
            tuple(
                replace(row, case=replace(row.case, key=f"search-{n}", question="مشترك"))
                for n in range(25)
            ),
            catalog.batches,
        )
        filters = {"q": "مشترك", "source": "question", "batch": "original"}
        with patch.object(views, "build_queue_catalog", return_value=catalog):
            first = self.get(data=filters)
            links = SearchMarkup(first.content.decode()).links
            next_links = [
                link for link in links if parse_qs(urlsplit(link).query).get("page") == ["2"]
            ]
            self.assertTrue(next_links)
            query = parse_qs(urlsplit(next_links[0]).query)
            for name, value in filters.items():
                self.assertEqual(query[name], [value])
            second = self.get(next_links[0])
        self.assertEqual(first.context["result"].total, 25)
        self.assertEqual(len(first.context["rows"]), 10)
        self.assertEqual(len(second.context["rows"]), 10)
        self.assertTrue(
            {row["hit"].case_key for row in first.context["rows"]}.isdisjoint(
                row["hit"].case_key for row in second.context["rows"]
            )
        )

    def test_source_text_is_escaped_and_retains_unicode_and_line_endings(self):
        from apps.editorial_search import views

        catalog = build_queue_catalog()
        row = catalog.rows[0]
        original = '\n  إِجَابَةٌ عَـلَى سؤال\r\n\te\u0301 <script>alert("x")</script>  '
        catalog = QueueCatalog(
            (replace(row, case=replace(row.case, question=original)),), catalog.batches
        )
        with patch.object(views, "build_queue_catalog", return_value=catalog):
            response = self.get(data={"q": "اجابة علي", "source": "question"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"][0]["hit"].fields[0].text, original)
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "&#13;")
        self.assertNotContains(response, "<script>")
        self.assertIn(original, "".join(SearchMarkup(response.content.decode()).text))
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_invalid_queries_fail_before_loading_fixtures(self):
        from apps.editorial_search import views

        with patch.object(views, "build_queue_catalog") as build:
            for suffix in (
                "?q=a&q=b",
                "?source=draft&source=question",
                "?batch=a&batch=b",
                "?page=1&page=2",
                "?source=unknown",
                "?file=C:/secret",
                "?q=%00",
                "?q=%7f",
                "?q=%0a",
                "?q=%C2%85",
                "?q=" + "a" * 81,
                "?page=0",
                "?page=-1",
                "?page=01",
                "?page=1.0",
                "?page=21",
                "?page=",
                "?page=%D9%A1",
                "?batch=../private",
            ):
                with self.subTest(suffix=suffix):
                    response = self.get(reverse("editorial_search:index") + suffix)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response["Cache-Control"], "no-store")
            build.assert_not_called()

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2)
    def test_too_many_fields_fail_safely_before_loading(self):
        from apps.editorial_search import views

        with patch.object(views, "build_queue_catalog") as build:
            response = self.get(data={"q": "x", "source": "draft", "page": "1"})
        self.assertEqual(response.status_code, 400)
        build.assert_not_called()

    def test_unknown_batch_and_expected_source_failure_do_not_expose_internals(self):
        from apps.editorial_search import views

        self.assertEqual(self.get(data={"q": "x", "batch": "unknown"}).status_code, 400)
        for error in (WorkbenchDataError("private-path"), HistoryDataError("private-path")):
            with patch.object(views, "build_queue_catalog", side_effect=error):
                response = self.get(data={"q": "x"})
            self.assertEqual(response.status_code, 503)
            self.assertNotContains(response, "private-path", status_code=503)
            self.assertEqual(response["Cache-Control"], "no-store")

    def test_guard_runs_before_loading_on_remote_or_production_requests(self):
        from apps.editorial_search import views

        with patch.object(views, "build_queue_catalog") as build:
            for name in ("editorial_search:index", "editorial_search:style"):
                url = reverse(name)
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
                with override_settings(SETTINGS_MODULE="config.settings.production"):
                    self.assertEqual(self.get(url).status_code, 404)
            build.assert_not_called()

    def test_safe_methods_ipv6_and_stylesheet(self):
        for name in ("editorial_search:index", "editorial_search:style"):
            url = reverse(name)
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                response = getattr(self.client, method)(
                    url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                )
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Allow"], "GET, HEAD")
            response = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
        self.assertEqual(
            self.client.get(
                reverse("editorial_search:index"), HTTP_HOST="[::1]", REMOTE_ADDR="::1"
            ).status_code,
            200,
        )
        css = self.get(reverse("editorial_search:style"))
        self.assertIn("text/css", css["Content-Type"])
        self.assertEqual(self.get(reverse("editorial_search:style") + "?file=x").status_code, 400)
