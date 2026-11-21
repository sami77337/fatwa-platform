"""Native form/reader composition with actual middleware and current scan pins."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.material_import import tests as import_fixtures
from apps.material_import.models import ImportBatch
from apps.research_library import editor
from apps.research_library import services as library
from apps.research_library import test_support as library_fixtures
from apps.research_library.models import LibraryBlob, LibraryVersion
from tests.casework.test_http import hidden

from . import services
from .middleware import UploadSecurityResponses
from .models import QuarantinedFile
from .test_support import RAW, ScannerMixin

FEATURES = {
    **import_fixtures.FEATURES,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_LINKS_ENABLED": True,
    "MIDDLEWARE": [
        "apps.upload_security.middleware.UploadSecurityResponses",
        *import_fixtures.FEATURES["MIDDLEWARE"],
    ],
}


@override_settings(**FEATURES)
class NativeUploadBoundaryTests(ScannerMixin, import_fixtures.ImportFixture, TransactionTestCase):
    def engine(self):
        original = services.invoke

        def invoke(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            return original(*args, **kwargs)

        return patch.object(services, "invoke", side_effect=invoke)

    def library_save(self, client, page):
        return client.post(
            "/casework/staff/",
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "action": "rl_save",
                "case_ref": self.receipt["public_ref"],
                "namespace": "native-library",
                "external_id": "native-book",
                "revision": "1",
                "evidence_version": "1",
                "expected_version": "0",
                "request_key": str(uuid.uuid4()),
                **{
                    key: value
                    for key, value in library_fixtures.payload().items()
                    if key != "synthetic"
                },
                "source_file": SimpleUploadedFile("native.txt", RAW, content_type="text/plain"),
            },
        )

    def test_library_native_scan_precedes_outer_command_and_render_transaction(self):
        client = self.login()
        page = import_fixtures.post(
            client, {"action": "rl_open", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(page.status_code, 200, page.content)
        with self.engine():
            response = self.library_save(client, page)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(bytes(LibraryBlob.objects.get().original), RAW)

    def test_import_native_envelope_scans_before_its_native_outer_transaction(self):
        client = self.login()
        page = import_fixtures.post(
            client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(page.status_code, 200, page.content)
        import json

        raw = json.dumps([import_fixtures.source_row()], ensure_ascii=False).encode()
        with self.engine():
            response = client.post(
                "/casework/staff/",
                {
                    "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                    "action": "mi_upload",
                    "case_ref": self.receipt["public_ref"],
                    "state": hidden(page, "state"),
                    "namespace": "synthetic-import",
                    "provenance": "مصدر اصطناعي",
                    "rights_basis": "اختبار فقط",
                    "synthetic": "yes",
                    "source_file": SimpleUploadedFile(
                        "records.json", raw, content_type="application/json"
                    ),
                },
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(bytes(ImportBatch.objects.get().raw), raw)

    def test_enhanced_answer_editor_scans_before_transaction_and_keeps_literal_human_text(self):
        client = self.login()
        page = import_fixtures.post(
            client, {"action": "answer_media", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(page.status_code, 200, page.content)
        with self.engine():
            response = client.post(
                "/casework/staff/",
                {
                    "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                    "action": "answer_media_save",
                    "case_ref": self.receipt["public_ref"],
                    "revision": "1",
                    "evidence_version": "1",
                    "text": "  أصل تحرير بشري\r\n ",
                    "retain": "no",
                    "synthetic_only": "yes",
                    "answer_file": SimpleUploadedFile("answer.txt", RAW, content_type="text/plain"),
                },
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.scanner.calls), 1)
        self.assertEqual(
            bytes(AnswerPart.objects.get(ordinal=1).original), "  أصل تحرير بشري\r\n ".encode()
        )
        self.assertEqual(bytes(AnswerPart.objects.get(ordinal=2).original), RAW)

    def test_last_native_renderer_cannot_commit_library_version_after_scan_revocation(self):
        client = self.login()
        page = import_fixtures.post(
            client, {"action": "rl_open", "case_ref": self.receipt["public_ref"]}
        )
        render = editor.render

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.scanner.current = replace(
                self.scanner.current, engine_version="SYNTHETIC-render-revoked"
            )
            return response

        with patch.object(editor, "render", side_effect=revoke):
            response = self.library_save(client, page)
        self.assertIn(response.status_code, {404, 409})
        self.assertFalse(LibraryVersion.objects.exists())
        self.assertFalse(LibraryBlob.objects.exists())
        self.assertEqual(bytes(QuarantinedFile.objects.get().original), RAW)

    def test_private_get_head_and_range_require_current_receipt_and_live_domain_rights(self):
        saved = self.approve(
            self.write(file_bytes=RAW, filename="native.txt", media_type="text/plain")
        )
        client = self.login()
        path = f"/casework/staff/library/{saved['version_id']}/file/"
        self.assertEqual(client.get(path).content, RAW)
        self.assertEqual(client.head(path).status_code, 200)
        # Preserve the domain's existing range behavior; a scan receipt never
        # grants either READ or a bypass of its conditional/range handler.
        self.scanner.current = replace(
            self.scanner.current, signature_version="SYNTHETIC-withdrawn"
        )
        for method, extra in (
            (client.get, {}),
            (client.head, {}),
            (client.get, {"HTTP_RANGE": "bytes=0-9"}),
        ):
            with self.subTest(method=method, extra=extra):
                response = method(path, **extra)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(RAW, response.content)

    def test_http_collector_has_no_outer_transaction_and_discards_late_or_streamed_bytes(self):
        saved = self.approve(
            self.write(file_bytes=RAW, filename="native.txt", media_type="text/plain")
        )
        request = RequestFactory().get("/casework/staff/")

        def reader(stream=False, revoke=False):
            def response(request):
                self.assertFalse(connection.in_atomic_block)
                raw = library.file_content(**self.common, version_id=saved["version_id"])["raw"]
                if revoke:
                    self.scanner.current = replace(
                        self.scanner.current, engine_version="SYNTHETIC-late"
                    )
                return StreamingHttpResponse([raw]) if stream else HttpResponse(raw)

            return response

        self.assertEqual(UploadSecurityResponses(reader())(request).content, RAW)
        streaming = UploadSecurityResponses(reader(stream=True))(request)
        self.assertEqual(streaming.status_code, 404)
        self.assertEqual(streaming["Referrer-Policy"], "no-referrer")
        response = UploadSecurityResponses(reader(revoke=True))(request)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn(RAW, response.content)
