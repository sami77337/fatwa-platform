from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class IdentityRegistryRecoveryTests(TransactionTestCase):
    def test_nonempty_history_and_fresh_current_trust(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["nonempty_tables"], 6)
        self.assertEqual(
            result["denial_checks"],
            {"missing_authority": 1, "missing_identity_provider": 1, "revoked_current_reader": 1},
        )
        self.assertEqual(result["denied_read_count"], 3)
        self.assertTrue(result["positive_reads_after_denial"])
