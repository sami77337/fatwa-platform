"""Actual portal and source-history pages must issue usable current-session URLs."""

import re
from html import unescape

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.source_case_intake import http_tests as source_http
from tests.casework.test_http import post

from .test_signed_links import FEATURES, LinkAssertions, PrivateOriginalFixture


@override_settings(
    **{
        **FEATURES,
        "FATWA_REQUESTER_PORTAL_ENABLED": True,
        "FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED": True,
    }
)
class RequesterPortalLinksTests(LinkAssertions, PrivateOriginalFixture, TransactionTestCase):
    def test_actual_portal_links_read_and_download_exact_parts_and_question_files(self):
        original = self.originals()
        page = self.requester.get("/casework/status/")
        self.assertTemplateUsed(page, "requester_portal/portal.html")
        self.assertContains(page, 'id="authorized-answer"')
        other = self.requester_for(self.receipt)
        for path in (
            f"/casework/status/answer-media/{self.part.pk}/",
            f"/casework/status/attachments/{self.attachment['id']}/",
        ):
            with self.subTest(path=path):
                inline = self.signed_url(page, path)
                self.exact_range(self.requester, inline, self.raw)
                downloads = [
                    unescape(value)
                    for value in re.findall(r'<a href="([^"]+)" download>', page.content.decode())
                    if value.startswith(path)
                ]
                self.assertEqual(len(downloads), 1)
                download = downloads[0]
                self.check_signed_url(download, path)
                self.assertNotEqual(inline, download)
                response = self.requester.get(download)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, self.raw)
                self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
                self.denied_file(other.get(inline), self.raw)
                self.denied_file(other.head(download), self.raw)
        self.assertEqual(self.originals(), original)


@override_settings(
    **{
        **FEATURES,
        "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
        "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED": True,
    }
)
class SourceHistoryLinksTests(LinkAssertions, TransactionTestCase):
    open = source_http.SourceDeskHTTPTests.open
    upload = source_http.SourceDeskHTTPTests.upload

    def setUp(self):
        super().setUp()
        source_http.SourceDeskHTTPTests.setUp(self)
        self.directory.projection_epoch = lambda: repr(self.directory.current)

    def test_native_source_upload_detail_and_timeline_use_same_authorized_original(self):
        raw = b"synthetic original question attachment\n" * 3
        detail = self.upload(
            self.open(self.root), attachment=SimpleUploadedFile("synthetic.txt", raw, "text/plain")
        )
        self.assertTemplateUsed(detail, "source_case_intake/desk.html")
        row = CaseAttachment.objects.get()
        path = f"/casework/staff/attachments/{row.pk}/"
        self.assertContains(detail, "مرفق محفوظ:")
        detail_url = self.signed_url(detail, path)
        self.exact_range(self.client, detail_url, raw)
        timeline = post(
            self.client,
            "/casework/staff/",
            {"action": "source_timeline", "case_ref": self.root["public_ref"]},
            detail,
        )
        self.assertTemplateUsed(timeline, "source_case_intake/desk.html")
        self.assertContains(timeline, 'data-evidence-version="2"')
        timeline_url = self.signed_url(timeline, path)
        self.exact_range(self.client, timeline_url, raw)
        self.directory.grant(source_http.services.REVIEW_SCOPE)
        for url in (detail_url, timeline_url):
            self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-4"), raw)
            self.denied_file(self.client.head(url), raw)
        self.assertEqual(CaseAttachment.objects.get().sha256, row.sha256)
