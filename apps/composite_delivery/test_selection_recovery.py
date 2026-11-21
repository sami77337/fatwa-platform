from django.test import TransactionTestCase, override_settings

from . import selection_recovery
from .test_selection import FEATURES


@override_settings(**FEATURES)
class SelectionRecoveryTests(TransactionTestCase):
    def test_restored_choice_retains_originals_and_signed_history_under_fresh_current_trust(self):
        pins = selection_recovery.populate()
        self.assertNotIn("private_key", str(pins))
        result = selection_recovery.verify_restored(pins)
        self.assertEqual(
            result["denial_checks"],
            {
                "disabled_choices": 1,
                "missing_identity_provider": 1,
                "missing_capabilities": 1,
                "revoked_current_reader": 1,
            },
        )
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["canonical_queue_history_unchanged"])
