from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class CitationRecoveryTests(TransactionTestCase):
    def test_nonempty_lineage_and_reconstituted_current_authority(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(set(pins["tables"]), set(recovery_support.TABLES))
        self.assertEqual(result["denied_reads"], 2)
        self.assertEqual(result["denied_read_count"], 2)
        self.assertEqual(
            result["denial_checks"], {"missing_authority": 1, "withdrawn_source_cite": 1}
        )
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertEqual(result["status"], "PASS")
