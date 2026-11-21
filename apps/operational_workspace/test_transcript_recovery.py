from django.test import TransactionTestCase, override_settings

from . import transcript_recovery_support
from .transcript_test_support import TRANSCRIPT_FEATURES


@override_settings(**TRANSCRIPT_FEATURES)
class OperationalTranscriptRecoveryTests(TransactionTestCase):
    def test_editorial_meaning_and_withdrawn_history_requires_fresh_roles_and_rights(self):
        pins = transcript_recovery_support.populate()
        result = transcript_recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 13)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["meaning_approver_is_actual_mufti"])
        self.assertTrue(result["canonical_sources_and_immutable_history_unchanged"])
