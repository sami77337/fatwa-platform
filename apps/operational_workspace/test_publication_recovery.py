from django.test import TransactionTestCase, override_settings

from . import publication_recovery_support
from .publication_test_support import PUBLICATION_FEATURES


@override_settings(**PUBLICATION_FEATURES)
class OperationalPublicationRecoveryTests(TransactionTestCase):
    def test_mufti_prepared_copy_and_organizer_decisions_need_fresh_current_grants(self):
        pins = publication_recovery_support.populate()
        result = publication_recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 13)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["mufti_prepared_body_unchanged"])
