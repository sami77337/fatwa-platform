from django.test import TransactionTestCase

from . import recovery_support


class MaterialAPIRecoveryTests(TransactionTestCase):
    def test_actual_api_restored_adapter_uses_current_grants_without_writes(self):
        result = recovery_support.verify_restored(recovery_support.populate())
        self.assertEqual(result["denied_read_count"], 4)
        self.assertEqual(result["denial_checks"], {"disabled_api": 1, "missing_authority": 1, "missing_identity_provider": 1, "revoked_release_actor": 1})
        self.assertTrue(result["positive_reads_after_denial"])
