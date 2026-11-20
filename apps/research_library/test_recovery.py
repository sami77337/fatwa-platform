"""Real external originals and fresh policy reconstruction for recovery readers."""

import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.private_media.filesystem import BACKEND, FileSystemStorage

from . import recovery_support
from .models import LibraryBlob
from .test_support import FEATURES


@override_settings(**FEATURES)
class LibraryRecoveryTests(TransactionTestCase):
    def test_nonempty_external_seed_and_new_readers_preserve_exact_versions_and_rights(self):
        with tempfile.TemporaryDirectory(prefix="library-recovery-readers-") as folder:
            source = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=source):
                pins = json.loads(json.dumps(recovery_support.populate()))
            self.assertIsNone(settings.FATWA_RESEARCH_LIBRARY_AUTHORITY)
            self.assertEqual(LibraryBlob.objects.count(), 2)
            self.assertFalse(LibraryBlob.objects.exclude(storage_backend=BACKEND).exists())
            self.assertFalse(LibraryBlob.objects.filter(original__isnull=False).exists())
            # New adapter and freshly reconstructed trust; no writer or fixture
            # admission is reused. The aggregate drill performs encrypted restore.
            reader = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=reader):
                actual = recovery_support.verify_restored(pins)
            self.assertEqual(
                actual,
                {
                    "table_count": 4,
                    "case_count": 1,
                    "blob_count": 2,
                    "item_count": 2,
                    "version_count": 4,
                    "decision_count": 5,
                    "public_version_count": 1,
                    "draft_denied_count": 2,
                },
            )
            encoded = json.dumps(pins)
            self.assertNotIn("credential", encoded)
            self.assertNotIn('"token"', encoded)
            self.assertIsNone(settings.FATWA_RESEARCH_LIBRARY_AUTHORITY)
