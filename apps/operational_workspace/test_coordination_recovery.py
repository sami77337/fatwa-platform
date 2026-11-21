from django.test import TransactionTestCase, override_settings

from . import coordination_recovery_support as recovery
from .coordination_test_support import COORDINATION_FEATURES


@override_settings(**COORDINATION_FEATURES)
class OperationalCoordinationRecoveryTests(TransactionTestCase):
    def test_restored_priority_and_assignment_require_current_actual_role_and_grants(self):
        result = recovery.verify_restored(recovery.populate())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 9)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["original_sources_and_history_unchanged"])
