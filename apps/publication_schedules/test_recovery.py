from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class ScheduleRecoveryTests(TransactionTestCase):
    def test_nonempty_history_fresh_grants_and_readonly_verification(self):
        pins = recovery_support.populate()
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        result = recovery_support.verify_restored(pins)
        self.assertEqual(
            result["denial_checks"],
            {"missing_authority": 1, "missing_identity_provider": 1, "revoked_current_reader": 1},
        )
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["history_and_canonical_unchanged"])
