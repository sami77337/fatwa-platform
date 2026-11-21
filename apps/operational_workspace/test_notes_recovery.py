from django.test import TransactionTestCase, override_settings

from . import notes_recovery_support
from .notes_test_support import NOTE_FEATURES


@override_settings(**NOTE_FEATURES)
class OperationalNotesRecoveryTests(TransactionTestCase):
    def test_actual_notes_are_preserved_without_restoring_identity_or_current_grants(self):
        pins = notes_recovery_support.populate()
        result = notes_recovery_support.verify_restored(pins)
        self.assertEqual(notes_recovery_support.TABLES, ())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 7)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["canonical_source_and_metadata_history_unchanged"])
