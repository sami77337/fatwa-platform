"""Integrated forms, actual byte routes and complete rendered-response boundaries."""

import uuid
from unittest.mock import patch
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.client import encode_multipart

from apps.delivery_queue.services import synthetic_queue_atomic
from apps.library_preview import services as preview
from tests.casework.test_http import hidden, post

from . import editor, public, services, views
from .models import LibraryDecision, LibraryItem, LibraryVersion
from .test_support import FEATURES, LibraryFixture, payload, video


@override_settings(**FEATURES)
class LibraryHTTPTests(LibraryFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        credential = {
            "editor": "synthetic-editor-credential-32-characters",
            "other": "synthetic-reviewer-credential-32-characters",
            "publisher": "synthetic-publisher-credential-32-characters",
        }[subject]
        self.assertEqual(
            post(client, "/casework/staff/login/", {"credential": credential}, login).status_code,
            303,
        )
        return client, client.get("/casework/staff/")

    def action(self, client, page, action, **fields):
        values = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "action": action,
            "case_ref": self.receipt["public_ref"],
            **fields,
        }
        return client.post(
            "/casework/staff/",
            urlencode(values, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )

    def test_actual_native_create_independent_review_release_reader_and_download(self):
        client, home = self.login()
        opened = self.action(client, home, "rl_open")
        self.assertContains(opened, "إضافة مادة ومصدرها")
        values = {k: v for k, v in payload().items() if k != "synthetic"}
        raw = "نص ملف اصطناعي\r\nدون تعديل".encode()
        saved = client.post(
            "/casework/staff/",
            {
                "csrfmiddlewaretoken": hidden(opened, "csrfmiddlewaretoken"),
                "action": "rl_save",
                "case_ref": self.receipt["public_ref"],
                "namespace": "native-library",
                "external_id": "native-book",
                "revision": "1",
                "evidence_version": "1",
                "expected_version": "0",
                "request_key": str(uuid.uuid4()),
                **values,
                "source_file": SimpleUploadedFile("native.txt", raw, content_type="text/plain"),
            },
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        version = LibraryVersion.objects.get()
        self.assertContains(saved, "الملف محفوظ، ولم تُتح قراءة")
        self.assertEqual(client.get(f"/casework/staff/library/{version.pk}/file/").status_code, 404)
        for subject, command, count, minutes, uses in (
            ("other", "REVIEW", 0, 0, []),
            ("publisher", "APPROVE", 1, 30, sorted(services.USES)),
            ("publisher", "RELEASE", 2, 15, []),
        ):
            reviewer, page = self.login(subject)
            detail = self.action(reviewer, page, "rl_item", version_id=str(version.pk))
            self.assertEqual(detail.status_code, 200, detail.content)
            result = self.action(
                reviewer,
                detail,
                "rl_decide",
                version_id=str(version.pk),
                command=command,
                expected_actions=str(count),
                revision="1",
                evidence_version="1",
                request_key=str(uuid.uuid4()),
                note="مراجعة بشرية مستقلة للنسخة والحقوق",
                minutes=str(minutes),
                uses=uses,
                confirmed="yes",
            )
            self.assertEqual(result.status_code, 200, result.content)
        download = client.get(f"/casework/staff/library/{version.pk}/download/")
        self.assertEqual(download.content, raw)
        self.assertIn("attachment", download["Content-Disposition"])
        public_client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        url = f"/library-preview/materials/{version.item.public_id}/1/"
        response = public_client.get(url)
        self.assertContains(response, payload()["title"])
        self.assertNotContains(response, self.receipt["public_ref"])
        self.assertNotContains(response, payload()["rights_basis"])
        self.assertEqual(public_client.get(url + "file/?download=1").content, raw)
        self.assertEqual(public_client.head(url + "file/").content, b"")

    def test_public_metadata_without_file_rights_shows_no_play_or_download_controls(self):
        row = self.release(
            self.write(
                payload=payload("VIDEO"),
                file_bytes=video(),
                filename="test.webm",
                media_type="video/webm",
            ),
            uses=["PUBLIC_METADATA"],
        )
        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        url = f"/library-preview/materials/{row['public_id']}/1/"
        page = client.get(url)
        self.assertContains(page, "لا يوجد ملف مصرح بفتحه")
        self.assertNotContains(page, "<video")
        self.assertNotContains(page, "تنزيل الملف")
        self.assertEqual(client.get(url + "file/").status_code, 404)
        self.assertEqual(client.get(url + "file/?download=1").status_code, 404)

    def test_browser_empty_file_control_creates_new_version_without_replacing_original(self):
        raw = b"synthetic original with preserved line endings\r\n"
        original = self.release(
            self.write(
                file_bytes=raw, filename="original.txt", media_type="text/plain"
            )
        )
        client, page = self.login()
        editing = self.action(client, page, "rl_edit", version_id=original["version_id"])
        self.assertContains(editing, 'id="library-save"')
        values = {
            "csrfmiddlewaretoken": hidden(editing, "csrfmiddlewaretoken"),
            "action": "rl_save",
            "case_ref": self.receipt["public_ref"],
            "namespace": original["namespace"],
            "external_id": original["external_id"],
            "revision": "1",
            "evidence_version": "1",
            "expected_version": "1",
            "request_key": str(uuid.uuid4()),
            **{key: value for key, value in payload().items() if key != "synthetic"},
            "title": "نسخة ثانية مستقلة بلا استبدال ملف الأصل",
            "edition_label": "نسخة ثانية",
        }
        boundary = "NativeEmptyFileControl"
        ending = f"--{boundary}--\r\n".encode()
        # Chromium includes this part for an untouched optional file input.
        # Django places it in POST as an empty string, not in FILES.
        empty_file = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="source_file"; '
            'filename=""\r\nContent-Type: application/octet-stream\r\n\r\n\r\n'
        ).encode()
        body = encode_multipart(boundary, values)
        self.assertTrue(body.endswith(ending))
        body = body[: -len(ending)] + empty_file + ending
        response = client.post(
            "/casework/staff/", body, content_type=f"multipart/form-data; boundary={boundary}"
        )
        self.assertEqual(response.status_code, 200, response.content)
        first = LibraryVersion.objects.get(pk=original["version_id"])
        second = LibraryVersion.objects.get(item=first.item, number=2)
        self.assertEqual(second.previous_id, first.pk)
        self.assertEqual(second.blob_id, first.blob_id)
        self.assertEqual(second.filename, first.filename)
        self.assertEqual(first.payload, payload())
        self.assertEqual(second.payload["title"], values["title"])
        self.assertFalse(second.decisions.exists())
        self.assertEqual(
            client.get(f"/casework/staff/library/{second.pk}/file/").status_code, 404
        )
        self.assertEqual(
            client.get(f"/casework/staff/library/{first.pk}/file/").content, raw
        )
        public_url = f"/library-preview/materials/{first.item.public_id}/1/"
        self.assertEqual(client.get(public_url + "file/").content, raw)
        self.assertEqual(client.get(public_url.replace("/1/", "/2/")).status_code, 404)
        replay = client.post(
            "/casework/staff/", body, content_type=f"multipart/form-data; boundary={boundary}"
        )
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(LibraryVersion.objects.filter(item=first.item).count(), 2)
        first.item.case.refresh_from_db()
        self.assertEqual(first.item.case.revision, 1)
        self.assertEqual(first.item.case.evidence_version, 1)

    def test_no_file_form_rejects_nonempty_duplicate_and_file_text_ambiguity(self):
        client, page = self.login()
        values = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "action": "rl_save",
            "case_ref": self.receipt["public_ref"],
            "namespace": "native-empty-file-validation",
            "external_id": "test-source",
            "revision": "1",
            "evidence_version": "1",
            "expected_version": "0",
            "request_key": str(uuid.uuid4()),
            **{key: value for key, value in payload().items() if key != "synthetic"},
        }
        for source in (
            "not-a-file",
            ["", ""],
            ["", SimpleUploadedFile("test.txt", b"synthetic", content_type="text/plain")],
        ):
            with self.subTest(source=type(source).__name__):
                response = client.post("/casework/staff/", {**values, "source_file": source})
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(LibraryItem.objects.exists())
        self.assertFalse(LibraryVersion.objects.exists())

    def test_read_permission_is_independent_from_download_permission(self):
        row = self.release(
            self.write(
                file_bytes=b"readable synthetic", filename="readable.txt", media_type="text/plain"
            ),
            uses=["READ", "PUBLIC_METADATA", "PUBLIC_CONTENT"],
        )
        client, _ = self.login()
        self.assertEqual(
            client.get(f"/casework/staff/library/{row['version_id']}/file/").status_code, 200
        )
        self.assertEqual(
            client.get(f"/casework/staff/library/{row['version_id']}/download/").status_code,
            404,
        )
        url = f"/library-preview/materials/{row['public_id']}/1/file/"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.get(url + "?download=1").status_code, 404)

    def test_csrf_unknown_fields_disable_and_remote_boundaries(self):
        client, page = self.login()
        self.assertEqual(
            client.post(
                "/casework/staff/", {"action": "rl_open", "case_ref": self.receipt["public_ref"]}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.action(client, page, "rl_open", provider_id="self-granted").status_code, 400
        )
        with override_settings(FATWA_RESEARCH_LIBRARY_ENABLED=False):
            self.assertEqual(self.action(client, page, "rl_open").status_code, 409)
        self.assertEqual(
            Client(REMOTE_ADDR="192.0.2.1", HTTP_HOST="127.0.0.1")
            .get("/library-preview/materials/")
            .status_code,
            403,
        )
        self.assertEqual(client.post("/library-preview/materials/").status_code, 405)

    def test_late_native_render_withdrawal_rolls_back_and_returns_no_source(self):
        row = self.approve(
            self.write(file_bytes=b"private-file", filename="private.txt", media_type="text/plain")
        )
        client, page = self.login()
        original_render = editor.render

        def revoked(*args, **kwargs):
            self.decide(row, "WITHDRAW")
            return original_render(*args, **kwargs)

        with patch.object(editor, "render", revoked):
            response = self.action(client, page, "rl_item", version_id=row["version_id"])
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(payload()["title"].encode(), response.content)
        self.assertFalse(LibraryDecision.objects.filter(action="WITHDRAW").exists())

    def test_late_public_render_permission_revocation_discards_all_html(self):
        row = self.release(
            self.write(file_bytes=b"public-file", filename="public.txt", media_type="text/plain")
        )
        original_render = views.render

        def revoked(*args, **kwargs):
            self.authority.denied.add("RELEASE")
            return original_render(*args, **kwargs)

        with patch.object(views, "render", revoked):
            response = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(
                f"/library-preview/materials/{row['public_id']}/1/"
            )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(payload()["title"].encode(), response.content)

    def test_current_material_pins_absence_against_late_callback_insert(self):
        count = 0

        def insert_after_lookup(values):
            nonlocal count
            if values["action"] == "VIEW" and values["external_id"] == "absent":
                count += 1
                if count == 2:
                    self.write(external_id="absent")

        self.authority.hook = insert_after_lookup
        with self.assertRaisesRegex(Exception, "library_head_changed"):
            services.current_material(
                **self.common, namespace="synthetic-library", external_id="absent"
            )
        self.assertFalse(LibraryItem.objects.exists())

    def test_reader_composes_only_under_the_verified_owned_queue_transaction(self):
        row = self.release(self.write(), uses=["PUBLIC_METADATA"])
        with synthetic_queue_atomic():
            with public.public_projection() as snapshot:
                self.assertEqual(snapshot.read(row["version_id"])["title"], payload()["title"])
        with transaction.atomic():
            with self.assertRaises(preview.PreviewUnavailable):
                with public.public_projection():
                    self.fail("arbitrary transaction must not bypass ownership preflight")
