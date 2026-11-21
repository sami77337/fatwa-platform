from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class CitationGatewayRecoveryTests(TransactionTestCase):
    def test_nonempty_audit_derivatives_restore_requires_fresh_processing_grants(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["denied_reads"], 12)
        self.assertEqual(result["denied_read_count"], 12)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["original_bytes_preserved"])
        self.assertEqual(result["real_provider_quality"], "NOT_EVALUATED")
