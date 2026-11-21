from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class DestinationRecoveryTests(TransactionTestCase):
    def test_fresh_connection_reads_exact_retained_history_and_current_denials_without_writes(self):
        pins = recovery_support.populate()
        self.assertTrue(all(pins["owned"].values()))
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["denied_read_count"], 9)
        self.assertEqual(result["event_count"], 13)
        self.assertTrue(result["source_and_delivery_rows_unchanged"])
        self.assertFalse(result["external_publication_verified"])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
                [list(recovery_support.TRIGGERS)],
            )
            self.assertEqual({row[0] for row in cursor.fetchall()}, set(recovery_support.TRIGGERS))
        call_command(
            "makemigrations", "publication_destinations", check=True, dry_run=True, verbosity=0
        )
