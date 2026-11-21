from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class MfaRecoveryTests(TransactionTestCase):
    def test_restored_history_keeps_consumed_recovery_but_never_resumes_authentication(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["denied_read_count"], 14)
        self.assertTrue(result["restored_authentication_rejected"])
        self.assertTrue(result["consumed_recovery_preserved"])
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["original_bytes_preserved"])
