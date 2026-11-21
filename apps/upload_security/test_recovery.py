from django.test import TransactionTestCase

from . import recovery_support


class UploadSecurityRecoveryTests(TransactionTestCase):
    def test_restored_scan_history_preserves_originals_and_requires_fresh_runtime_and_rights(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["denied_read_count"], 14)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["original_bytes_preserved"])
        self.assertTrue(result["fresh_scanner_and_domain_authority_required"])
        self.assertFalse(result["external_scan_during_restore_read"])
        self.assertFalse(result["real_engine_verified"])
