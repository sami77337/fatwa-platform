"""Actual private originals survive GC and join exact-schema recovery references."""

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.case_attachments import storage_bindings
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery import service as recovery
from apps.private_media.filesystem import FileSystemStorage

from . import services
from .models import LibraryBlob, LibraryVersion
from .test_support import FEATURES, LibraryFixture


class ObservedStorage(FileSystemStorage):
    @contextmanager
    def binding_lock(self, digest):
        with super().binding_lock(digest):
            depth = getattr(self, "depth", 0)
            self.depth = depth + 1
            try:
                yield
                if depth == 0:
                    self.committed_bindings.append(
                        (connection.in_atomic_block, LibraryBlob.objects.filter(pk=digest).exists())
                    )
            finally:
                self.depth = depth


@override_settings(**FEATURES)
class LibraryStorageTests(LibraryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory(prefix="library-originals-")
        self.addCleanup(folder.cleanup)
        self.storage = ObservedStorage(Path(folder.name) / "private", synthetic_fixtures_only=True)
        self.storage.committed_bindings = []
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)
        self.raw = "أصل خاص للمكتبة\r\n لا يتغير ".encode()

    def create_file(self):
        return self.write(file_bytes=self.raw, filename="source.txt", media_type="text/plain")

    def test_external_reference_lock_is_held_until_commit_and_gc_preserves_bytes(self):
        row = self.create_file()
        self.assertEqual(self.storage.committed_bindings, [(False, True)])
        blob = LibraryBlob.objects.get(pk=row["file"]["sha256"])
        self.assertIsNone(blob.original)
        path = self.storage.root / "objects" / blob.storage_key
        os.utime(path, (time.time() - 7200,) * 2)
        self.assertTrue(storage_bindings.live_references(blob.storage_backend, blob.storage_key))
        result = self.storage.collect_orphans(
            storage_bindings.live_references, grace_seconds=3600, dry_run=False
        )
        self.assertEqual(result, [{"key": blob.storage_key, "status": "REFERENCED_PRESERVED"}])
        self.approve(row)
        self.assertEqual(
            services.file_content(**self.common, version_id=row["version_id"])["raw"], self.raw
        )

    def test_nested_external_write_requires_preacquired_exact_binding(self):
        with synthetic_queue_atomic(), self.assertRaisesRegex(
            cases.CaseConflict, "storage_lock_requires_outer_transaction_boundary"
        ):
            self.create_file()
        self.assertEqual(LibraryVersion.objects.count(), 0)
        with services.material_bindings([self.raw]), synthetic_queue_atomic():
            row = self.create_file()
            self.assertEqual(self.storage.committed_bindings, [])
        self.assertEqual(self.storage.committed_bindings, [(False, True)])
        self.assertTrue(LibraryVersion.objects.filter(pk=row["version_id"]).exists())

    def test_recovery_uses_hash_primary_key_and_actual_external_reference(self):
        row = self.create_file()
        with recovery.connect() as db:
            refs = recovery.references(db)
        blob = LibraryBlob.objects.get()
        self.assertEqual(
            [ref for ref in refs if ref["table"] == "research_library_libraryblob"],
            [
                {
                    "table": "research_library_libraryblob",
                    "id": row["file"]["sha256"],
                    "backend": blob.storage_backend,
                    "key": blob.storage_key,
                    "sha256": blob.sha256,
                    "size": len(self.raw),
                }
            ],
        )
        self.assertNotIn("LIBRARY_BLOB", storage_bindings.OWNERS)

    def test_omitted_owner_app_preserves_existing_original_and_blocks_capture(self):
        self.create_file()
        blob = LibraryBlob.objects.get()
        path = self.storage.root / "objects" / blob.storage_key
        os.utime(path, (time.time() - 7200,) * 2)
        installed = storage_bindings.apps.is_installed
        with patch.object(
            storage_bindings.apps,
            "is_installed",
            side_effect=lambda name: name != "apps.research_library" and installed(name),
        ):
            result = self.storage.collect_orphans(
                storage_bindings.live_references, grace_seconds=3600, dry_run=False
            )
            self.assertEqual(result[0]["status"], "REFERENCE_UNAVAILABLE_PRESERVED")
            with recovery.connect() as db, self.assertRaisesRegex(
                recovery.RecoveryError, "media_owner_registry_unavailable"
            ):
                recovery.references(db)
        self.assertEqual(path.read_bytes(), self.raw)

    def test_missing_external_bytes_deny_current_read_without_dropping_metadata(self):
        row = self.approve(self.create_file())
        blob = LibraryBlob.objects.get()
        (self.storage.root / "objects" / blob.storage_key).unlink()
        with self.assertRaises(cases.CaseConflict):
            services.file_content(**self.common, version_id=row["version_id"])
        self.assertEqual(LibraryVersion.objects.count(), 1)
        self.assertEqual(LibraryBlob.objects.count(), 1)
