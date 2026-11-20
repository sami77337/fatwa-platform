import json

from django.test import TransactionTestCase

from . import recovery_support


class LifecycleRecoveryTests(TransactionTestCase):
    def test_nonempty_population_and_new_policy_readers_preserve_exact_pins(self):
        pins = json.loads(json.dumps(recovery_support.populate()))
        self.assertEqual(pins["cases"][0]["state"], "CLOSED")
        self.assertEqual(pins["cases"][1]["state"], "ARCHIVED")
        self.assertEqual(pins["cases"][2]["state"], "OPEN")
        self.assertEqual(recovery_support.verify_restored(pins)["event_count"], 6)
        for secret in ("token", "credential", "private_key"):
            self.assertNotIn(secret, json.dumps(pins))
