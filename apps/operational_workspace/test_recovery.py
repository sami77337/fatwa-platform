from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class OperationalRecoveryTests(TransactionTestCase):
    def test_nonempty_source_states_reopen_only_under_new_current_operational_grants(self):
        pins = recovery_support.populate()
        self.assertEqual(recovery_support.TABLES, ())
        self.assertEqual(pins["expected"]["counts"]["delivery"], 1)
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 7)
        self.assertTrue(result["canonical_source_and_delivery_history_unchanged"])
        self.assertTrue(result["positive_reads_after_denial"])
