"""Explicit offline rights, real packages and late-revocation HTTP boundaries."""

import base64
import io
import json
import uuid
import zipfile
from hashlib import sha256
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from . import offline
from .models import LibraryDecision
from .test_support import FEATURES, LibraryFixture, payload, video


@override_settings(**{**FEATURES, "FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED": True})
class OfflineLibraryTests(LibraryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def source(self, **changes):
        options = dict(
            file_bytes="نص اصطناعي متاح دون اتصال\r\n".encode(),
            filename="source.txt",
            media_type="text/plain",
        )
        return self.release(self.write(**{**options, **changes}))

    def packet_path(self, row):
        return offline.ROOT + f"packets/{row['version_id']}/"

    def archive_path(self, *rows):
        return (
            offline.ROOT
            + "package/?"
            + urlencode({"version": [r["version_id"] for r in rows]}, doseq=True)
        )

    def test_packet_contains_only_exact_public_fields_and_actual_original_bytes(self):
        row = self.source()
        response = self.client.get(self.packet_path(row))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["X-Content-SHA256"], sha256(response.content).hexdigest())
        packet = response.json()
        self.assertEqual(packet["material"]["version_id"], row["version_id"])
        self.assertEqual(
            base64.b64decode(packet["file_base64"]), "نص اصطناعي متاح دون اتصال\r\n".encode()
        )
        self.assertEqual(packet["material"]["file"]["sha256"], row["file"]["sha256"])
        for secret in (
            self.receipt["case_id"],
            self.receipt["public_ref"],
            "subject_id",
            "auth_epoch",
            "rights_basis",
            "provenance",
            "private-",
        ):
            self.assertNotIn(secret, response.content.decode())
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(self.client.head(self.packet_path(row)).content, b"")

    def test_runtime_offline_is_independent_from_public_read_and_download(self):
        row = self.source()
        self.authority.denied.add("OFFLINE")
        self.assertEqual(self.client.get(self.packet_path(row)).status_code, 404)
        self.assertEqual(self.client.get(self.archive_path(row)).status_code, 404)
        self.assertEqual(self.client.get(offline.ROOT + "catalog/").json()["materials"], [])
        detail = f"/library-preview/materials/{row['public_id']}/{row['number']}/"
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.get(detail + "file/?download=1").status_code, 200)
        self.authority.denied.add("DOWNLOAD")
        self.assertNotContains(self.client.get(detail), "تنزيل الملف المصرح به")
        self.assertEqual(self.client.get(detail + "file/?download=1").status_code, 404)
        self.assertEqual(self.client.get(detail + "file/").status_code, 200)

    def test_offline_approval_is_required_even_with_runtime_authority(self):
        row = self.release(
            self.write(
                file_bytes=b"synthetic source", filename="source.txt", media_type="text/plain"
            ),
            uses=["PUBLIC_METADATA", "PUBLIC_CONTENT", "DOWNLOAD"],
        )
        self.assertEqual(self.client.get(self.packet_path(row)).status_code, 404)
        self.assertEqual(self.client.get(offline.ROOT + "catalog/").json()["materials"], [])

    def test_descriptive_offline_copy_has_no_hidden_file_or_unreleased_text(self):
        row = self.release(
            self.write(payload=payload(recorded_text="نص لم يأذن بعرضه")),
            uses=["PUBLIC_METADATA", "OFFLINE"],
        )
        response = self.client.get(self.packet_path(row))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["material"]["file"])
        self.assertEqual(response.json()["material"]["recorded_text"], "")
        self.assertEqual(response.json()["file_base64"], "")

    def test_readable_archive_contains_selected_text_video_and_integrity_manifest(self):
        first = self.source(
            payload=payload(title="اختيار نصي", recorded_text="<script>unsafe()</script>")
        )
        second = self.source(
            payload=payload("VIDEO", title="اختيار مرئي"),
            file_bytes=video(),
            filename="movie.webm",
            media_type="video/webm",
        )
        third = self.source(payload=payload(title="مادة غير مختارة"))
        response = self.client.get(self.archive_path(first, second))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(sha256(response.content).hexdigest(), response["X-Content-SHA256"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "index.html",
                    "archive.css",
                    "manifest.json",
                    "manifest.sha256",
                    "files/001.txt",
                    "files/002.webm",
                },
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(
                [r["material"]["version_id"] for r in manifest["materials"]],
                [first["version_id"], second["version_id"]],
            )
            self.assertNotIn(third["version_id"], archive.read("manifest.json").decode())
            self.assertEqual(archive.read("files/002.webm"), video())
            self.assertEqual(
                sha256(archive.read("files/001.txt")).hexdigest(), first["file"]["sha256"]
            )
            self.assertEqual(
                archive.read("manifest.sha256").decode().split()[0],
                sha256(archive.read("manifest.json")).hexdigest(),
            )
            html = archive.read("index.html").decode()
            self.assertIn("&lt;script&gt;unsafe()&lt;/script&gt;", html)
            self.assertNotIn("<script>", html)
            self.assertIn(first["public_id"], html)
            self.assertIn("<video controls", html)

    def test_archive_is_atomic_when_selected_source_is_missing_or_revoked(self):
        row = self.source()
        self.assertEqual(
            self.client.get(self.archive_path(row, {"version_id": str(uuid.uuid4())})).status_code,
            404,
        )
        self.decide(row, "REVOKE")
        response = self.client.get(self.archive_path(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"PK", response.content)
        self.assertNotIn(row["payload"]["title"].encode(), response.content)

    def test_late_archive_revoke_discards_zip_and_rolls_back_nested_change(self):
        row = self.source()
        before = LibraryDecision.objects.count()
        original = offline._archive

        def late(packets):
            raw = original(packets)
            self.decide(row, "WITHDRAW")
            return raw

        with patch.object(offline, "_archive", side_effect=late):
            response = self.client.get(self.archive_path(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"PK", response.content)
        self.assertEqual(LibraryDecision.objects.count(), before)

    def test_pwa_assets_are_bounded_and_never_contain_materials_or_private_context(self):
        row = self.source()
        shell = self.client.get(offline.ROOT)
        self.assertEqual(shell.status_code, 200)
        self.assertContains(shell, 'rel="manifest"')
        self.assertNotIn(row["version_id"], shell.content.decode())
        self.assertIn("worker-src 'self'", shell["Content-Security-Policy"])
        manifest = self.client.get(offline.ROOT + "manifest.webmanifest").json()
        self.assertEqual(manifest["scope"], offline.ROOT)
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue({"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]})
        for size in (192, 512):
            response = self.client.get(offline.ROOT + f"icon-{size}.png")
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response.content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(
            self.client.get(offline.ROOT + "sw.mjs")["Service-Worker-Allowed"], offline.ROOT
        )
        for path in (
            offline.ROOT + "unknown.mjs",
            offline.ROOT + "app.mjs?version=1",
            self.archive_path(row, row),
            offline.ROOT + "package/",
        ):
            self.assertIn(self.client.get(path).status_code, {400, 404})
        self.assertEqual(self.client.post(offline.ROOT).status_code, 405)
        self.assertEqual(self.client.get(offline.ROOT, REMOTE_ADDR="192.0.2.1").status_code, 403)
        with override_settings(FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED=False):
            self.assertEqual(self.client.get(offline.ROOT).status_code, 404)
            self.assertEqual(self.client.get(self.packet_path(row)).status_code, 404)
