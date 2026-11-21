import shutil
from pathlib import Path

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.ai_gateway import recovery_support as ai_recovery
from apps.canonical_search import recovery_support as search_recovery
from apps.record_suppression import recovery_support as suppression_recovery

from . import recovery_support
from .catalog import DerivedDenied


class DerivedRecoveryTests(TransactionTestCase):
    def populate(self):
        pins = recovery_support.populate()
        self.addCleanup(shutil.rmtree, Path(pins["journal_root"]))
        return pins

    def test_restored_clearances_and_new_children_need_current_floor_and_fresh_grants(self):
        pins = self.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["nonempty_tables"], 2)
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["human_edits_and_approval_preserved"])
        self.assertTrue(result["cleared_identifiers_not_reactivated"])

    def test_two_independent_current_floors_compose_existing_search_ai_and_source_verifiers(self):
        search_pins, ai_pins = search_recovery.populate(), ai_recovery.populate()
        pins = self.populate()
        suppression_pins = suppression_recovery.populate()
        self.addCleanup(shutil.rmtree, Path(suppression_pins["journal_root"]))
        with override_settings(
            FATWA_DERIVED_MAINTENANCE_AUTHORITY=None,
            FATWA_RECORD_SUPPRESSION_AUTHORITY=None,
        ):
            identity = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
            privacy = settings.FATWA_DATA_PRIVACY_ENABLED
            with self.assertRaises(DerivedDenied):
                with suppression_recovery.current_floor(suppression_pins):
                    search_recovery.verify_restored(search_pins)
            with (
                recovery_support.current_floor(pins),
                suppression_recovery.current_floor(suppression_pins),
            ):
                self.assertIsNone(settings.FATWA_DERIVED_MAINTENANCE_AUTHORITY)
                self.assertIsNone(settings.FATWA_RECORD_SUPPRESSION_AUTHORITY)
                self.assertIs(settings.FATWA_CASEWORK_IDENTITY_PROVIDER, identity)
                self.assertEqual(settings.FATWA_DATA_PRIVACY_ENABLED, privacy)
                search_recovery.verify_restored(search_pins)
                ai_result = ai_recovery.verify_restored(ai_pins)
                self.assertTrue(ai_result["positive_reads_after_denial"])
                restored = suppression_recovery.verify_restored(suppression_pins)
                self.assertTrue(restored["positive_reads_after_denial"])
                self.assertTrue(
                    recovery_support.verify_restored(pins)["positive_reads_after_denial"]
                )
