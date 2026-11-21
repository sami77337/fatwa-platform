"""Stateless link verification must use restored sources and current trust."""

from django.test import TransactionTestCase

from . import recovery_support


class SignedLinkRecoveryTests(TransactionTestCase):
    def test_current_private_link_protocol_uses_exact_sources_without_saving_grants(self):
        pins = recovery_support.populate()
        self.assertEqual(recovery_support.TABLES, ())
        self.assertEqual(recovery_support.FUNCTIONS, ())
        self.assertEqual(recovery_support.TRIGGERS, ())
        self.assertEqual(set(pins), {"case", "versions", "tables"})
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["denial_checks"], recovery_support.DENIAL_CHECKS)
        self.assertEqual(result["denied_read_count"], 18)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["canonical_and_history_unchanged"])
        self.assertFalse(result["serialized_session_or_link_grants"])
