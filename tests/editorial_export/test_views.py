"""The local export UI preserves case identity and guards fixture access."""

import hashlib
import os
from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class PageLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


@override_settings(ALLOWED_HOSTS=["localhost", "remote.invalid"])
class ExportViewsTests(SimpleTestCase):
    base = "/dev/editorial-export"
    filenames = ("report.json", "cases.csv", "batches.csv", "manifest.json")

    def get(self, path, **extra):
        return self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **extra)

    def test_index_lists_downloads_and_failed_batches_with_no_rows(self):
        response = self.get(self.base)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="ar"')
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, "اصطناعية")
        self.assertNotContains(response, "<script")
        self.assertNotContains(response, "<form")
        links = PageLinks(response.content.decode()).links
        for filename in self.filenames:
            self.assertIn(self.base + "/" + filename, links)
        report = self.get(self.base + "/report.json").json()
        self.assertEqual(response.context["case_count"], len(report["cases"]))
        self.assertEqual(response.context["batch_count"], len(report["batches"]))
        failed_batches = [batch for batch in report["batches"] if batch["error_code"]]
        self.assertTrue(failed_batches)
        for batch in failed_batches:
            self.assertEqual(batch["record_count"], 0)
            self.assertContains(response, batch["batch_id"])
            self.assertContains(response, batch["error_code"])
        for hold in report["holds"]:
            self.assertContains(response, hold)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_case_links_preserve_identity_and_packet_bytes(self):
        index = self.get(self.base)
        report = self.get(self.base + "/report.json").json()
        links = PageLinks(index.content.decode()).links
        keys = []
        for item in report["cases"]:
            packet = item["packet"]
            key = packet["identity"]["case_key"]
            keys.append(key)
            self.assertEqual(item["navigation"]["case_key"], key)
            self.assertIn(item["navigation"]["packet_path"], links)
            self.assertContains(index, key)
            self.assertContains(index, packet["source"]["input_sha256"])
            self.assertContains(index, item["packet_sha256"])
            detail = self.get(item["navigation"]["packet_path"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.context["packet"]["identity"], packet["identity"])
            self.assertEqual(detail["X-Packet-SHA256"], item["packet_sha256"])
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(link.startswith(("/", "#")) for link in links))

    def test_downloads_are_deterministic_attachments_with_byte_digests(self):
        for filename in self.filenames:
            with self.subTest(filename=filename):
                path = self.base + "/" + filename
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, self.get(path).content)
                self.assertEqual(
                    response["Content-Disposition"], f'attachment; filename="{filename}"'
                )
                self.assertEqual(
                    response["X-Export-SHA256"], hashlib.sha256(response.content).hexdigest()
                )
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response["Cache-Control"], "no-store")
                expected_type = "text/csv" if filename.endswith(".csv") else "application/json"
                self.assertTrue(response["Content-Type"].startswith(expected_type))
                head = self.client.head(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                self.assertEqual(head["X-Export-SHA256"], response["X-Export-SHA256"])

    def test_guards_reject_before_building_fixtures(self):
        with patch(
            "apps.editorial_export.views.build_export",
            side_effect=AssertionError("fixture accessed"),
        ):
            for path in (self.base, self.base + "/report.json"):
                with self.subTest(path=path):
                    self.assertEqual(
                        self.client.get(
                            path, HTTP_HOST="remote.invalid", REMOTE_ADDR="127.0.0.1"
                        ).status_code,
                        404,
                    )
                    self.assertEqual(
                        self.client.get(
                            path, HTTP_HOST="localhost", REMOTE_ADDR="192.0.2.4"
                        ).status_code,
                        404,
                    )
                    with patch.dict(os.environ, FATWA_PRODUCTION="1"):
                        self.assertEqual(self.get(path).status_code, 404)
                    with override_settings(FATWA_PRODUCTION=True):
                        self.assertEqual(self.get(path).status_code, 404)
                    with override_settings(SETTINGS_MODULE="config.settings.production"):
                        self.assertEqual(self.get(path).status_code, 404)
                    for method in ("post", "put", "patch", "delete", "options"):
                        response = getattr(self.client, method)(
                            path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                        )
                        self.assertEqual(response.status_code, 405)

    def test_query_and_unknown_files_fail_before_building_fixtures(self):
        with patch(
            "apps.editorial_export.views.build_export",
            side_effect=AssertionError("fixture accessed"),
        ):
            for path in (self.base, self.base + "/report.json"):
                for query in (
                    "?q=x",
                    "?q=x&q=y",
                    "?filename=report.json",
                    "?synthetic_fixtures_only=true",
                    "?q=",
                ):
                    with self.subTest(path=path, query=query):
                        response = self.get(path + query)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response["Cache-Control"], "no-store")
                with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1):
                    self.assertEqual(self.get(path + "?a=1&b=2").status_code, 400)
            for filename in (
                "secrets.json",
                "report.JSON",
                "cases.csv.exe",
                "../../config/settings/base.py",
            ):
                self.assertEqual(self.get(self.base + "/" + filename).status_code, 404)

    def test_invalid_fixture_fails_without_partial_download_or_diagnostics(self):
        from apps.editorial_export.services import ExportError

        with patch(
            "apps.editorial_export.views.build_export",
            side_effect=ExportError("SECRET internal failure"),
        ):
            for path in (self.base, *(self.base + "/" + name for name in self.filenames)):
                response = self.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertNotContains(response, "SECRET", status_code=503)
                self.assertNotIn("Content-Disposition", response)
                self.assertEqual(response["Cache-Control"], "no-store")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
