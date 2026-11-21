"""The restored reader uses only saved identifiers and fresh explicit trust."""

from django.test import TransactionTestCase

from . import recovery_support


class ClassificationRecoveryTests(TransactionTestCase):
    def test_existing_classifications_are_immutable_and_grant_no_restored_authority(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], len(recovery_support.DENIALS))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertTrue(result["unclassified_work_requires_fresh_explicit_grant"])
