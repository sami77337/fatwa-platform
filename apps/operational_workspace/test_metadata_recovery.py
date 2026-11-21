from django.test import TransactionTestCase, override_settings

from . import metadata_recovery_support
from .metadata_test_support import METADATA_FEATURES


@override_settings(**METADATA_FEATURES)
class OperationalMetadataRecoveryTests(TransactionTestCase):
    def test_preserved_metadata_requires_fresh_actual_actor_and_exact_classification_grants(self):
        pins = metadata_recovery_support.populate()
        result = metadata_recovery_support.verify_restored(pins)
        self.assertEqual(metadata_recovery_support.TABLES, ())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 10)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["canonical_sources_and_immutable_history_unchanged"])
