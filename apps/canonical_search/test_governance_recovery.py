"""The aggregate encrypted drill adds fresh-process proof to this adapter check."""

from django.db import connection, connections
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.casework.models import CaseEvent

from . import governance_recovery_support


class SearchGovernanceRecoveryTests(TransactionTestCase):
    def test_populated_records_reopen_with_current_denials_and_no_write_or_rebuild(self):
        pins = governance_recovery_support.populate()
        before = CaseEvent.objects.count()
        connections.close_all()
        with CaptureQueriesContext(connection) as queries:
            result = governance_recovery_support.verify_restored(pins)
        self.assertEqual(result["verified_dictionary_versions"], 2)
        self.assertEqual(
            result["denial_checks"],
            {
                "missing_authority": 2,
                "missing_identity_provider": 2,
                "disabled_feature": 2,
                "revoked_current_reader": 2,
            },
        )
        self.assertEqual(result["denied_read_count"], 8)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["governance_history_unchanged"])
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertFalse(
            any(
                query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for query in queries
            )
        )
