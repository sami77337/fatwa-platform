"""Fresh-connection read-only adapter; the aggregate drill adds encrypted restore."""

from django.db import connection, connections
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.casework.models import CaseEvent

from . import benchmark_recovery_support


class CanonicalBenchmarkRecoveryTests(TransactionTestCase):
    def test_nonempty_actual_benchmark_reopens_without_writes_or_restored_grants(self):
        pins = benchmark_recovery_support.populate()
        events = CaseEvent.objects.count()
        connections.close_all()
        with CaptureQueriesContext(connection) as queries:
            result = benchmark_recovery_support.verify_restored(pins)
        self.assertEqual(result["denied_read_count"], 12)
        self.assertEqual(
            result["denial_checks"],
            {
                "missing_benchmark_authority": 2,
                "missing_identity_provider": 2,
                "disabled_feature": 2,
                "missing_source_search_authority": 2,
                "revoked_read_action": 2,
                "revoked_current_reader": 2,
            },
        )
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["benchmark_history_unchanged"])
        self.assertEqual(result["actual_query_pairs"], 3)
        self.assertFalse(result["promotion_performed"])
        self.assertEqual(CaseEvent.objects.count(), events)
        self.assertFalse(
            any(
                row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for row in queries
            )
        )
