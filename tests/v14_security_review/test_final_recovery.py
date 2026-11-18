"""Real encrypted restoration checks new V14 tables and database guards."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.platform_recovery import service
from tests.casework import test_v11_maintenance as recovery_fixture


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
)
class V14SchemaRecovery(TransactionTestCase):
    setUp = recovery_fixture.MaintenanceIntegrationTests.setUp
    freeze = recovery_fixture.MaintenanceIntegrationTests.freeze
    capture = recovery_fixture.MaintenanceIntegrationTests.capture

    def test_encrypted_restore_preserves_v14_schema_guards_and_original_private_bytes(self):
        schema = service.PostgresTools.schema
        seen = []

        def observe(tools, database, snapshot=None):
            result = schema(tools, database, snapshot)
            seen.append(result)
            return result

        with patch.object(service.PostgresTools, "schema", observe):
            recovery_fixture.MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(
                self
            )
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        for table in (
            "pdf_citations_pdfcitation",
            "pdf_citations_pdfcitationaction",
            "arabic_search_eval_evaluationrevision",
            "arabic_search_eval_evaluationdecision",
            "classification_review_editorialbinding",
        ):
            self.assertIn(f"CREATE TABLE public.{table}".encode(), seen[1])
        for guard in (
            "pdf_citations_guard",
            "pdf_citations_action_guard",
            "ase_revision_guard",
            "ase_decision_guard",
            "classification_editorial_binding_guard",
            "classification_editorial_action_guard",
        ):
            self.assertIn(f"CREATE FUNCTION public.{guard}()".encode(), seen[1])
            self.assertIn(f"CREATE TRIGGER {guard}".encode(), seen[1])
