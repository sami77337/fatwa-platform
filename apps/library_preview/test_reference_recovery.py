import json
import tempfile
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.private_media.filesystem import FileSystemStorage

from . import reference_recovery
from .reference_test_support import FEATURES


@override_settings(**FEATURES)
class ReferenceRecoveryTests(TransactionTestCase):
    def test_fresh_restored_reference_keeps_exact_originals_and_six_current_trust_denials(self):
        with tempfile.TemporaryDirectory(prefix="reference-recovery-") as folder:
            with override_settings(
                FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(
                    Path(folder) / "private", synthetic_fixtures_only=True
                )
            ):
                pins = json.loads(json.dumps(reference_recovery.populate()))
                connection.close()
                with CaptureQueriesContext(connection) as queries:
                    result = reference_recovery.verify_restored(pins)
                self.assertEqual(result["denied_read_count"], 6)
                self.assertTrue(result["positive_reads_after_denial"])
                self.assertEqual(result["new_table_count"], 0)
                self.assertEqual(result["restored_authority_grants"], 0)
                self.assertTrue(result["source_and_originals_unchanged"])
                for row in queries:
                    self.assertNotIn(
                        row["sql"].lstrip().split(" ", 1)[0].upper(), {"INSERT", "UPDATE", "DELETE"}
                    )
