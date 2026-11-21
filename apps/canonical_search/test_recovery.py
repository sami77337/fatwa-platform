"""Adapter smoke test; the integrated parent drill supplies fresh-process restore evidence."""

from django.test import TransactionTestCase

from . import recovery_support


class SearchRecoveryAdapterTests(TransactionTestCase):
    def test_nonempty_real_index_roundtrip_and_current_denials(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["verified_documents"], 3)
        self.assertEqual(result["denials"], {"missing_authority": True, "inactive_identity": True})
        self.assertEqual(result["denial_checks"], {"missing_authority": 1, "inactive_identity": 1})
        self.assertEqual(result["denied_read_count"], 2)
        self.assertIs(result["positive_reads_after_denial"], True)
