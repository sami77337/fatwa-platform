from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class DevelopmentTaxonomyRecoveryTests(TransactionTestCase):
    def test_nonempty_versions_and_actual_bindings_restore_without_implied_authority(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["nonempty_tables"], 7)
        self.assertEqual(result["denied_read_count"], 4)
        self.assertEqual(
            result["denial_checks"],
            {
                "missing_authority": 1,
                "missing_identity_provider": 1,
                "revoked_current_reader": 1,
                "revoked_mapping_authority": 1,
            },
        )
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["actual_binding_rollback_preserved"])
