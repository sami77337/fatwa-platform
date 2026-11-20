import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings

from apps.private_media.filesystem import FileSystemStorage

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class MediaRecoveryTests(TransactionTestCase):
    def test_nonempty_recovery_readers_and_current_trust_denials_preserve_rows_and_bytes(self):
        with tempfile.TemporaryDirectory(prefix="recording-recovery-") as folder:
            storage = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                pins = recovery_support.populate()
                before = {
                    path.name: path.read_bytes() for path in (storage.root / "objects").iterdir()
                }
                result = recovery_support.verify_restored(pins)
                self.assertEqual(result["table_count"], 4)
                self.assertEqual(result["denied_read_count"], 9)
                self.assertTrue(result["positive_reads_after_denial"])
                self.assertEqual(
                    before,
                    {path.name: path.read_bytes() for path in (storage.root / "objects").iterdir()},
                )
                self.assertTrue(all(pins["tables"].values()))
