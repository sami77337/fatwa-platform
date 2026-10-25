"""Packet modes use existing GET/HEAD guards and the selected case identity."""

import os
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.ids = []
        self.details = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "details":
            self.details.append("open" in attrs)


@override_settings(ALLOWED_HOSTS=["localhost", "remote.invalid"])
class PacketViewsTests(SimpleTestCase):
    def get(self, url, **extra):
        return self.client.get(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def detail(self, key="history"):
        return reverse("editorial_workbench:detail", args=[key])

    def test_follow_workbench_to_packet_export_print_and_back_preserving_selection(self):
        detail = self.get(self.detail() + "?revision=7&before=11&after=4&q=sample")
        packet_url = detail.context["packet_url"]
        self.assertContains(detail, "حزمة مراجعة السجل")
        self.assertIn("packet=html", packet_url)
        html = self.get(packet_url)
        self.assertEqual(html.status_code, 200)
        self.assertEqual(
            html.context["packet"]["selection"], {"revision": 7, "before": 11, "after": 4}
        )
        self.assertIn("q=sample", html.context["workbench_url"])
        self.assertNotIn("packet=", html.context["workbench_url"])
        for label in (
            "الاستلام الأصلي",
            "اللقطات الثابتة",
            "أسئلة المتابعة",
            "أحداث المراجعة المحفوظة",
        ):
            self.assertContains(html, label)
        export = self.get(html.context["packet_json_url"])
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.json(), html.context["packet"])
        self.assertIn("attachment;", export["Content-Disposition"])
        self.assertEqual(export["X-Content-Type-Options"], "nosniff")
        self.assertEqual(export["Cache-Control"], "no-store")
        self.assertEqual(export["X-Packet-SHA256"], html.context["packet_sha256"])
        self.assertEqual(export.content, self.get(html.context["packet_json_url"]).content)
        printable = self.get(html.context["packet_print_url"])
        self.assertEqual(printable.context["packet"], html.context["packet"])
        self.assertContains(printable, "Ctrl+P")
        self.assertTrue(all(Links(printable.content.decode()).details))
        self.assertNotContains(printable, "<script")
        parsed = Links(html.content.decode())
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        for link in parsed.links:
            if link.startswith("#"):
                self.assertIn(link[1:], parsed.ids)

    def test_each_existing_synthetic_case_has_a_complete_packet(self):
        from apps.editorial_workbench.services import build_cases, build_prepared_workbench

        for case in (*build_cases(), *build_prepared_workbench().cases):
            with self.subTest(case=case.key):
                response = self.get(self.detail(case.key) + "?packet=json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["identity"]["case_key"], case.key)
                html = self.get(self.detail(case.key) + "?packet=html")
                self.assertEqual(html.status_code, 200)
                self.assertContains(html, case.key)
                printable = self.get(self.detail(case.key) + "?packet=print")
                self.assertEqual(printable.status_code, 200)
                self.assertTrue(all(Links(printable.content.decode()).details))

    def test_packet_preserves_carriage_returns_and_initial_newline_in_escaped_html(self):
        from apps.editorial_workbench import views
        from apps.editorial_workbench.services import build_cases

        case = replace(
            build_cases()[0], question="\nسؤال\r\n<script>synthetic</script>", record=None
        )
        with patch.object(views, "build_cases", return_value=(case,)):
            for mode in ("html", "print"):
                with self.subTest(mode=mode):
                    response = self.get(self.detail() + "?packet=" + mode)
                    self.assertContains(
                        response, "<code>\nسؤال&#13;\n&lt;script&gt;synthetic&lt;/script&gt;</code>"
                    )
                    self.assertNotContains(response, "<script>")

    def test_packet_query_validation_and_missing_case_or_revision(self):
        for query, status in (
            ("packet=xml", 400),
            ("packet=", 400),
            ("packet=html&packet=json", 400),
            ("packet=json&file=private", 400),
            ("packet=json&revision=07", 400),
            ("packet=json&revision=3", 404),
            ("packet=json&before=1", 400),
        ):
            with self.subTest(query=query):
                self.assertEqual(self.get(self.detail() + "?" + query).status_code, status)
        self.assertEqual(
            self.get(reverse("editorial_workbench:index") + "?packet=json").status_code, 400
        )
        self.assertEqual(self.get(self.detail("unknown") + "?packet=json").status_code, 404)
        self.assertEqual(
            self.get(self.detail("intake-2") + "?packet=json&revision=1").status_code, 400
        )

    def test_all_packet_modes_keep_local_guards_safe_methods_and_no_database_reads(self):
        from apps.editorial_workbench import views

        with patch(
            "apps.intake_workflow.review.load_review_worklist", side_effect=AssertionError("read")
        ):
            for mode in ("html", "json", "print"):
                url = self.detail() + "?packet=" + mode
                self.assertEqual(self.get(url).status_code, 200)
                head = self.client.head(url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                for method in ("post", "put", "patch", "delete", "options", "trace"):
                    self.assertEqual(
                        getattr(self.client, method)(url, HTTP_HOST="localhost").status_code, 405
                    )
                with patch.object(views, "build_cases") as build:
                    for host, peer in (("remote.invalid", "127.0.0.1"), ("localhost", "10.0.0.1")):
                        self.assertEqual(
                            self.client.get(url, HTTP_HOST=host, REMOTE_ADDR=peer).status_code, 404
                        )
                    with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                        self.assertEqual(self.get(url).status_code, 404)
                    with override_settings(FATWA_PRODUCTION=True):
                        self.assertEqual(self.get(url).status_code, 404)
                    build.assert_not_called()

    def test_packet_escapes_source_text_and_fails_closed_on_invalid_output(self):
        from apps.editorial_workbench import views
        from apps.editorial_workbench.services import build_cases

        case = replace(
            build_cases()[0], question='<script>alert("synthetic")</script>', record=None
        )
        with patch.object(views, "build_cases", return_value=(case,)):
            html = self.get(self.detail() + "?packet=html")
            self.assertContains(html, "&lt;script&gt;")
            self.assertNotContains(html, "<script>")
        bad = replace(case, question="\ud800")
        with patch.object(views, "build_cases", return_value=(bad,)):
            response = self.get(self.detail() + "?packet=json")
            self.assertEqual(response.status_code, 503)
            self.assertContains(response, "تعذر", status_code=503)
