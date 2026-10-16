"""Wave5 contracts: D1 intake + D3 exact identity + D2 read-only Django preview."""

import os
import socket
import sqlite3
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse

from apps.editorial_demo.integration import build_preview_rows


class IntegratedPipelineTests(SimpleTestCase):
    # SimpleTestCase refuses database access. All inputs and source pins are synthetic.
    url = "/dev/editorial-preview/pipeline"

    def get(self, path=None, **kwargs):
        return self.client.get(path or self.url, HTTP_HOST="localhost", **kwargs)

    def test_actual_d1_d3_results_are_joined_by_exact_id(self):
        rows = build_preview_rows()
        self.assertEqual([r.external_id for r in rows], [
            "SYN-P01", "SYN-P02", "SYN-P03", "SYN-P04"
        ])
        self.assertEqual(rows[0].question, "  سؤال اصطناعي في الطهارة للمراجعة فقط  ")
        self.assertEqual(rows[0].status, "ready-for-editor")
        self.assertTrue(rows[0].draft_created)
        self.assertEqual(rows[0].references[0].status, "verified")
        self.assertIn("عنوان في فهرس", rows[0].references[0].citation)
        self.assertEqual(rows[1].status, "needs-editor-review")
        self.assertTrue(rows[1].draft_created)
        self.assertEqual(rows[1].references[0].status, "unverified")
        self.assertIsNone(rows[1].references[0].citation)
        self.assertEqual(rows[2].status, "needs-editor-review")
        self.assertFalse(rows[2].draft_created)  # Clip URL missing.
        self.assertEqual(rows[3].status, "blocked-invalid")
        self.assertFalse(rows[3].draft_created)  # Insecure/malformed clip URL.

    def test_no_network_or_database_for_composition(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
             patch.object(sqlite3, "connect", side_effect=AssertionError("db forbidden")):
            self.assertEqual(len(build_preview_rows()), 4)

    def test_routes_and_arabic_safe_list(self):
        self.assertEqual(resolve(self.url).url_name, "editorial_pipeline")
        self.assertEqual(reverse("editorial_pipeline"), self.url)
        response = self.get()
        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertContains(response, "SYN-P01")
        self.assertContains(response, "SYN-P02")
        self.assertContains(response, "SYN-P03")
        self.assertContains(response, "SYN-P04")
        self.assertNotContains(response, "SYN-001")
        self.assertContains(response, "بيانات اصطناعية")
        self.assertContains(response, "غير منشورة")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotContains(response, "<textarea")

    def test_detail_shows_exact_original_and_nonfatwa_reference(self):
        response = self.get(self.url + "/SYN-P01")
        self.assertEqual(resolve(self.url + "/SYN-P01").url_name, "editorial_pipeline_detail")
        self.assertContains(response, "  سؤال اصطناعي في الطهارة للمراجعة فقط  ")
        self.assertContains(response, "إحالة إلى عنوان في فهرس")
        self.assertContains(response, "ليس نص فتوى")
        self.assertNotContains(response, "demo-edition")
        self.assertNotContains(response, "synthetic-source")
        self.assertNotContains(response, "synthetic-heading")
        self.assertNotContains(response, "a" * 64)
        self.assertNotContains(response, "<textarea")
        self.assertNotContains(response, 'href="https://example.invalid')
        self.assertContains(response, "لا توجد إجابة")

    def test_unresolved_and_missing_media_never_look_approved(self):
        unresolved = self.get(self.url + "/SYN-P02")
        self.assertContains(unresolved, "غير محسومة")
        self.assertNotContains(unresolved, "إحالة إلى عنوان في فهرس")
        missing = self.get(self.url + "/SYN-P03")
        self.assertContains(missing, "لم يُنشأ سجل مسودة")
        self.assertContains(missing, "رابط المقطع")
        invalid = self.get(self.url + "/SYN-P04")
        self.assertContains(invalid, "مرفوض")
        self.assertContains(invalid, "لم يُنشأ سجل مسودة")

    def test_search_status_and_empty(self):
        filtered = self.get(self.url + "?status=needs-editor-review")
        self.assertContains(filtered, "SYN-P02")
        self.assertContains(filtered, "SYN-P03")
        self.assertNotContains(filtered, "SYN-P01")
        self.assertNotContains(filtered, "SYN-P04")
        searched = self.get(self.url + "?q=الطهارة")
        self.assertContains(searched, "SYN-P01")
        self.assertNotContains(searched, "SYN-P02")
        self.assertContains(self.get(self.url + "?q=nomatch"), "لا توجد سجلات مطابقة")

    def test_bounds_duplicate_params_and_missing_ident(self):
        for data in ({"q": "x" * 81}, {"q": "\x00"}, {"status": "published"},
                     {"status": ["ready-for-editor", "blocked-invalid"]},
                     {"unapproved": "1"}):
            self.assertEqual(self.get(data=data).status_code, 400)
        self.assertEqual(self.get(self.url + "/SYN-001").status_code, 404)
        self.assertEqual(self.get(self.url + "/not-found").status_code, 404)

    def test_read_only_head_local_and_production_guards(self):
        for path in (self.url, self.url + "/SYN-P01"):
            self.assertEqual(self.client.head(path, HTTP_HOST="localhost").content, b"")
            for verb in ("post", "put", "patch", "delete", "options"):
                resp = getattr(self.client, verb)(path, HTTP_HOST="localhost")
                self.assertEqual(resp.status_code, 405)
            self.assertEqual(self.get(path, REMOTE_ADDR="192.0.2.1").status_code, 404)
            with patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}):
                self.assertEqual(self.get(path).status_code, 404)
        with override_settings(ALLOWED_HOSTS=["*"]):
            self.assertEqual(self.client.get(self.url, HTTP_HOST="example.com").status_code, 404)

    def test_fail_closed_on_unavailable_pipeline(self):
        with patch("apps.editorial_demo.views.build_preview_rows", side_effect=ValueError("sensitive diagnostic")):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"sensitive diagnostic", response.content)
