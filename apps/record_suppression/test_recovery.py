import shutil
from pathlib import Path

from django.test import TransactionTestCase

from . import recovery_support


class SuppressionRecoveryTests(TransactionTestCase):
    def test_restored_current_case_and_deleted_answer_require_independent_floor(self):
        pins = recovery_support.populate()
        self.addCleanup(shutil.rmtree, Path(pins["journal_root"]))
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertTrue(result["positive_reads_after_denial"])
        self.assertTrue(result["preserved_originals"])

    def test_floor_scope_composes_an_existing_reader_without_administrative_grants(self):
        import uuid

        from django.conf import settings
        from django.test import override_settings

        from apps.casework import services as cases
        from apps.operational_workspace.test_support import Directory

        from .catalog import SuppressionDenied

        key = uuid.uuid4().hex
        receipt = cases.intake_case(
            original_question="قضية مستقلة من مكوّن قائم",
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        pins = recovery_support.populate()
        self.addCleanup(shutil.rmtree, Path(pins["journal_root"]))
        directory = Directory([receipt["public_ref"]])
        with override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=directory, FATWA_RECORD_SUPPRESSION_AUTHORITY=None
        ):
            original_privacy = settings.FATWA_DATA_PRIVACY_ENABLED

            def read():
                return cases.read_case(
                    case_id=receipt["case_id"],
                    provider=directory,
                    subject_id="mufti",
                    synthetic_fixtures_only=True,
                )

            with self.assertRaises(SuppressionDenied):
                read()
            with recovery_support.current_floor(pins):
                self.assertIsNone(settings.FATWA_RECORD_SUPPRESSION_AUTHORITY)
                self.assertIs(settings.FATWA_CASEWORK_IDENTITY_PROVIDER, directory)
                self.assertEqual(settings.FATWA_DATA_PRIVACY_ENABLED, original_privacy)
                self.assertEqual(read()["public_ref"], receipt["public_ref"])
