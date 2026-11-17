"""Actual forms/CSRF with no database access, storage writes or external adapters."""

import io
import json
import re
import time
from html import unescape
from unittest.mock import patch
from urllib.parse import urlencode
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, override_settings

from tests.fast8_transcript_queue.test_services import encode, segments

BASE = "/transcripts/"


def hidden(page, name):
    match = re.search(r'name="' + name + r'" value="([^"]+)"', page.content.decode())
    if not match:
        raise AssertionError("missing field: " + name)
    return unescape(match.group(1))


@override_settings(FATWA_TRANSCRIPT_WORKBENCH_ENABLED=True, SECRET_KEY="synthetic-test-secret")
class WorkbenchHTTPTests(SimpleTestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"FATWA_PRODUCTION": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = self.browser()

    def browser(self):
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def upload(self, rows=None, filename="synthetic.json", raw=None):
        page = self.client.get(BASE)
        response = self.client.post(
            BASE,
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "synthetic_only": "yes",
                "transcript": SimpleUploadedFile(
                    filename, raw if raw is not None else encode(rows or segments())
                ),
            },
        )
        return response

    def submit(self, page, action, *, client=None, **fields):
        return (client or self.client).post(
            BASE + "review/",
            urlencode(
                {
                    "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                    "state": hidden(page, "state"),
                    "action": action,
                    **fields,
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )

    def test_upload_edit_export_and_reimport_complete_native_form_journey(self):
        page = self.upload()
        self.assertEqual(page.status_code, 200)
        for text in ("مراجعة التفريغات", "قضية", "تنزيل الحزمة"):
            self.assertContains(page, text)
        page = self.submit(
            page,
            "revise",
            index=0,
            start_ms=18,
            end_ms=1017,
            text="ignored unless explicitly chosen",
        )
        self.assertEqual(page.status_code, 200)
        exported = self.submit(page, "export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported["Content-Type"], "application/zip")
        with ZipFile(io.BytesIO(exported.content)) as archive:
            reviewed = archive.read("reviewed.json")
            self.assertEqual(json.loads(reviewed)["items"][0]["text"], segments()[0]["text"])
            self.assertEqual(json.loads(reviewed)["items"][0]["start_ms"], 18)
        self.assertEqual(self.upload(raw=reviewed).status_code, 200)
        self.assertIn("no-store", exported["Cache-Control"])
        self.assertEqual(exported["X-Content-Type-Options"], "nosniff")

    def test_overlap_can_be_fixed_in_browser_and_export_is_blocked_until_then(self):
        rows = segments()
        rows[1]["start_ms"] = 1000
        page = self.upload(rows)
        self.assertContains(page, "تداخل بين مقطعين")
        self.assertNotContains(page, 'value="export"')
        self.assertEqual(self.submit(page, "export").status_code, 400)
        page = self.submit(page, "select", index=1)
        page = self.submit(page, "revise", index=1, start_ms=1017, end_ms=2019, text="")
        self.assertContains(page, 'value="export"')
        self.assertEqual(self.submit(page, "export").status_code, 200)

    def test_explicit_replacement_and_invalid_edit_preserve_review(self):
        page = self.upload()
        invalid = self.submit(page, "revise", index=0, start_ms=18, end_ms=0, text="")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(hidden(page, "state").split(":")[0], invalid.content.decode())
        page = self.submit(
            page,
            "revise",
            index=0,
            start_ms=17,
            end_ms=1017,
            text="نص جديد اصطناعي",
            replace_text="yes",
        )
        self.assertContains(page, "نص جديد اصطناعي")
        with ZipFile(io.BytesIO(self.submit(page, "export").content)) as archive:
            self.assertEqual(archive.read("original.json"), encode(segments()))

    def test_state_cannot_be_modified_replayed_in_other_browser_or_used_after_expiry(self):
        page = self.upload()
        self.assertEqual(
            self.submit(page, "export", state=hidden(page, "state") + "x").status_code, 400
        )
        foreign = self.browser()
        foreign_page = foreign.get(BASE)
        response = foreign.post(
            BASE + "review/",
            {
                "csrfmiddlewaretoken": hidden(foreign_page, "csrfmiddlewaretoken"),
                "state": hidden(page, "state"),
                "action": "export",
            },
        )
        self.assertEqual(response.status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + 1801):
            self.assertEqual(self.submit(page, "export").status_code, 400)

    def test_csrf_origin_duplicate_fields_and_extra_uploads_are_denied(self):
        self.assertEqual(self.client.post(BASE, {}).status_code, 403)
        page = self.upload()
        response = self.client.post(
            BASE + "review/",
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "state": hidden(page, "state"),
                "action": "export",
            },
            HTTP_ORIGIN="https://foreign.example",
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            BASE + "review/",
            urlencode(
                [
                    ("csrfmiddlewaretoken", hidden(page, "csrfmiddlewaretoken")),
                    ("state", hidden(page, "state")),
                    ("action", "export"),
                    ("action", "export"),
                ]
            ),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 400)

    def test_closed_local_profile_limits_and_private_error_responses(self):
        for kwargs, code in (
            ({"REMOTE_ADDR": "192.0.2.1"}, 403),
            ({"HTTP_HOST": "evil.example"}, 400),
            ({"CONTENT_LENGTH": "4000001"}, 413),
        ):
            with self.subTest(kwargs=kwargs):
                response = self.client.get(BASE, **kwargs)
                self.assertEqual(response.status_code, code)
                self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get(BASE + "?state=x").status_code, 400)
        self.assertEqual(self.client.get(BASE + "review/").status_code, 405)
        self.assertEqual(self.client.head(BASE).content, b"")
        with override_settings(FATWA_TRANSCRIPT_WORKBENCH_ENABLED=False):
            self.assertEqual(self.client.get(BASE).status_code, 503)
        with patch.dict("os.environ", {"FATWA_PRODUCTION": "1"}):
            self.assertEqual(self.client.get(BASE).status_code, 503)

    def test_malformed_oversized_and_untrusted_content_never_render_as_markup(self):
        self.assertEqual(self.upload(raw=b"invalid-json").status_code, 400)
        self.assertEqual(self.upload(raw=b"x" * 1_000_001).status_code, 413)
        self.assertEqual(self.upload(filename="synthetic.html").status_code, 400)
        rows = segments()
        rows[0]["text"] = '<script>alert("synthetic")</script>'
        page = self.upload(rows)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "<script>")
        self.assertContains(page, "&lt;script&gt;")
        self.assertIn("default-src 'none'", page["Content-Security-Policy"])

    def test_example_is_a_downloadable_valid_synthetic_input(self):
        example = self.client.get(BASE + "example/")
        self.assertEqual(example.status_code, 200)
        self.assertIn("attachment", example["Content-Disposition"])
        page = self.upload(raw=example.content)
        self.assertEqual(page.status_code, 200)
