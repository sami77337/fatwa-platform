"""Durable typed media all use the same case/evidence and authenticated private routes."""

from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.casework.models import Case, CaseEvidence
from apps.private_media.fixtures import synthetic_files

from . import services, views
from . import tests as legacy
from .models import CaseAttachment
from .tests import new_case, staff_common, upload


@override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
class MediaCaseTests(TransactionTestCase):
    def test_all_media_types_are_durable_private_originals_with_distinct_evidence(self):
        receipt = new_case()
        for index, (filename, media_type, raw) in enumerate(synthetic_files(), 1):
            row = upload(
                receipt, raw=raw, filename=filename, media_type=media_type, expected_revision=index
            )
            self.assertEqual(row["evidence_version"], index + 1)
            result = services.staff_read(**staff_common(receipt), attachment_id=row["id"])
            self.assertEqual(result["raw"], raw)
            self.assertEqual(result["media_type"], media_type)
        self.assertEqual(Case.objects.get().evidence_version, 9)
        self.assertEqual(CaseEvidence.objects.count(), 9)
        self.assertEqual(CaseAttachment.objects.count(), 8)


@override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
@override_settings(FATWA_CASEWORK_WEB_ENABLED=True, ROOT_URLCONF="apps.case_attachments.urls")
class MediaHTTPTests(TransactionTestCase):
    client_for = legacy.AttachmentHTTPTests.client_for

    def request_for(self, client, path):
        request = RequestFactory().get(path, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        request.COOKIES = {name: value.value for name, value in client.cookies.items()}
        request.META["CSRF_COOKIE"] = client.cookies["fatwa_casework_csrf"].value
        return request

    def test_each_media_get_reauthorizes_and_preserves_restrictive_headers(self):
        first, second = new_case(), new_case()
        client, page = self.client_for(first)
        other, _ = self.client_for(second)
        for index, (filename, media_type, raw) in enumerate(synthetic_files(), 1):
            row = upload(
                first, raw=raw, filename=filename, media_type=media_type, expected_revision=index
            )
            path = "/casework/status/attachments/" + row["id"] + "/"
            response = views.requester_file(self.request_for(client, path), row["id"])
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.content, raw)
            self.assertEqual(response["Content-Type"], media_type)
            self.assertIn("sandbox", response["Content-Security-Policy"])
            self.assertIn("no-store", response["Cache-Control"])
            denied = views.requester_file(self.request_for(other, path), row["id"])
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(raw, denied.content)
        from apps.casework import services as cases

        cases.revoke_access(
            **staff_common(first), requester_id=Case.objects.get(pk=first["case_id"]).requester_id
        )
        denied = views.requester_file(self.request_for(client, path), row["id"])
        self.assertEqual(denied.status_code, 404)
