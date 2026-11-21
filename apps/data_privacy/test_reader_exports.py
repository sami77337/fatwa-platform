"""A public label/read permits no implicit printable or downloaded content copy."""

from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.public_reader_tools import services as reader
from apps.public_reader_tools.test_support import FEATURES, ReaderFixture

from .public_derivative_test_support import PrivacyAssertions


@override_settings(**FEATURES)
class PublicReaderExportPrivacyTests(PrivacyAssertions, ReaderFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.enable_privacy()
        self.admit_known()
        self.privacy_grant("CASE", self.receipt["case_id"], "PUBLISH")
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.url = f"/library-preview/reading/{self.publication.pk}/"

    def export(self):
        return self.privacy_grant("PUBLICATION", self.publication.pk, "EXPORT", public=True)

    def denied(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.publication.body.encode(), response.content)
        self.assertNotIn("Content-Disposition", response)

    def test_native_read_and_reference_metadata_do_not_grant_content_export(self):
        page = self.client.get(self.url)
        self.assertContains(page, self.publication.body)
        self.assertNotContains(page, "فتح نسخة الطباعة المسموح بها")
        self.assertNotContains(page, "تنزيل نسخة النص المسموح بها")
        for route in ("save-reference/", "share-link/"):
            response = self.client.get(self.url + route)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("body", response.json())
        for route in ("print/", "print-permission/", "download/"):
            self.denied(self.client.get(self.url + route))
            self.denied(self.client.head(self.url + route))
        self.assert_originals()

    def test_exact_export_grant_allows_copy_until_revoked_without_changing_public_read(self):
        key = self.export()
        for route in ("print/", "download/"):
            self.assertContains(self.client.get(self.url + route), self.publication.body)
        del self.privacy_authority.grants[key]
        for route in ("print/", "download/"):
            self.denied(self.client.get(self.url + route))
        self.assertContains(self.client.get(self.url), self.publication.body)
        self.assert_originals()

    def test_revocation_after_text_composition_withholds_the_complete_response(self):
        key = self.export()
        original = reader.text_copy

        def compose_then_revoke(result):
            raw = original(result)
            del self.privacy_authority.grants[key]
            return raw

        with patch.object(reader, "text_copy", side_effect=compose_then_revoke):
            self.denied(self.client.get(self.url + "download/"))
        self.export()
        self.assertContains(self.client.get(self.url + "download/"), self.publication.body)
        self.assert_originals()
