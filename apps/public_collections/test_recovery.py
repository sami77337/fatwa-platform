from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES, CollectionFixture


@override_settings(**FEATURES)
class RecoveryContractTests(CollectionFixture, TransactionTestCase):
    def test_nonempty_exact_recovery_inventory_and_fresh_authority_contract(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(set(result["tables"]), set(recovery_support.TABLES))
        self.assertTrue(all(result["tables"].values()))
