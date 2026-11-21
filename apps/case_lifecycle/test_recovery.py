import json

from django.test import TransactionTestCase

from . import recovery_support


class LifecycleRecoveryTests(TransactionTestCase):
    def test_nonempty_population_and_new_policy_readers_preserve_exact_pins(self):
        pins = json.loads(json.dumps(recovery_support.populate()))
        self.assertEqual(pins["cases"][0]["state"], "CLOSED")
        self.assertEqual(pins["cases"][1]["state"], "ARCHIVED")
        self.assertEqual(pins["cases"][2]["state"], "OPEN")
        self.assertEqual(
            recovery_support.verify_restored(pins),
            {
                "table_count": 1,
                "case_count": 3,
                "event_count": 6,
                "denied_read_count": 9,
                "denial_checks": {
                    "missing_authority": 3,
                    "missing_identity_provider": 3,
                    "revoked_current_reader": 3,
                },
                "positive_reads_after_denial": True,
            },
        )
        for secret in ("token", "credential", "private_key"):
            self.assertNotIn(secret, json.dumps(pins))
