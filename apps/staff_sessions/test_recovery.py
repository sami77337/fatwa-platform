from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class StaffSessionRecoveryTests(TransactionTestCase):
    def test_restored_audit_preserves_sources_but_never_restores_session_authority(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["denied_read_count"], 8)
        self.assertTrue(result["restored_sessions_rejected"])
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["original_bytes_preserved"])
