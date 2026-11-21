from django.test import TransactionTestCase

from . import recovery_support


class PermissionRecoveryTests(TransactionTestCase):
    def test_restored_audit_and_templates_need_current_exact_runtime_and_identity(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertTrue(result["positive_reads_after_denial"])
