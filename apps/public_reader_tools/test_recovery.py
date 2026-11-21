import json
import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings

from apps.private_media.filesystem import FileSystemStorage

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class ReaderRecoveryTests(TransactionTestCase):
    def test_restored_text_tools_rebuild_trust_and_never_restore_device_bookmarks(self):
        with tempfile.TemporaryDirectory(prefix="reader-tool-recovery-") as folder:
            storage = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                pins = json.loads(json.dumps(recovery_support.populate()))
                result = recovery_support.verify_restored(pins)
                self.assertEqual(result["table_count"], 0)
                self.assertEqual(result["device_bookmarks_restored"], 0)
                self.assertEqual(result["denied_read_count"], 8)
                self.assertTrue(result["positive_reads_after_denial"])
                self.assertTrue(result["source_rows_and_original_bytes_unchanged"])
