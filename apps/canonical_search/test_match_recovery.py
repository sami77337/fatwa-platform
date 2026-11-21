"""The parent encrypted drill supplies restoration; this tests the real helper contract."""

import json

from django.db import connections
from django.test import TransactionTestCase

from . import match_recovery_support


class SearchMatchRecoveryTests(TransactionTestCase):
    def test_fresh_connection_reopens_exact_ranges_and_rechecks_each_current_permission(self):
        pins = json.loads(json.dumps(match_recovery_support.populate()))
        connections.close_all()
        result = match_recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denied_read_count"], 6)
        self.assertEqual(
            set(result["denial_checks"]),
            {
                "disabled_search",
                "missing_authority",
                "missing_identity",
                "revoked_open",
                "revoked_search",
                "revoked_case_scope",
            },
        )
        self.assertTrue(result["exact_question_and_answer_spans"])
        self.assertTrue(result["canonical_source_and_index_unchanged"])
        self.assertTrue(result["positive_reads_after_denial"])
