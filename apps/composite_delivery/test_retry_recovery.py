import json

from django.db import connections
from django.test import TransactionTestCase, override_settings

from . import retry_recovery
from .test_retry import FEATURES


@override_settings(**FEATURES)
class RetryRecoveryTests(TransactionTestCase):
    def test_fresh_connection_retains_failed_ancestors_signed_successor_and_current_trust_denials(
        self,
    ):
        pins = json.loads(json.dumps(retry_recovery.populate(), default=str))
        connections.close_all()
        result = retry_recovery.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["new_table_count"], 1)
        self.assertEqual(result["retry_rows"], 2)
        self.assertEqual(result["denied_read_count"], 6)
