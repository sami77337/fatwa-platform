"""Adapter-level consistency; the root harness performs the encrypted fresh-process drill."""

from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .tests import FEATURES


@override_settings(**FEATURES)
class RecoveryAdapterTests(TransactionTestCase):
    def test_real_service_seed_populates_all_seven_tables_and_current_readers_verify(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(len(result["tables"]), 7)
        self.assertTrue(result["current_authority_required"])
        self.assertFalse(result["scientific_approval_created"])
