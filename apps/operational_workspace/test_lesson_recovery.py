from django.test import TransactionTestCase, override_settings

from . import lesson_recovery_support
from .lesson_test_support import LESSON_FEATURES


@override_settings(**LESSON_FEATURES)
class OperationalLessonRecoveryTests(TransactionTestCase):
    def test_preserved_proposal_review_and_withdrawal_require_fresh_exact_grants(self):
        pins = lesson_recovery_support.populate()
        result = lesson_recovery_support.verify_restored(pins)
        self.assertEqual(lesson_recovery_support.TABLES, ())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 12)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["canonical_sources_and_immutable_history_unchanged"])
