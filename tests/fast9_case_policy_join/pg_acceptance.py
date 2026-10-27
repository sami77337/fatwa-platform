"""Opt-in only: not auto-collected by offline test discovery; never skip/xfail."""

from django.db import connection, transaction
from django.test import SimpleTestCase

from apps.fast9_case_policy_join.services import inspect_request
from apps.intake_workflow.guards import require_synthetic_write
from tools.fast9_case_policy_join.postgres_check import BASE


class SyntheticNonMutationAcceptance(SimpleTestCase):
    databases = {"default"}

    def test_composition_uses_no_database_and_keeps_owned_synthetic_rows_unchanged(self):
        context = require_synthetic_write(synthetic_fixtures_only=True)
        self.assertEqual(context.database_name, "test_" + BASE)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT current_database(), current_user")
                self.assertEqual(cursor.fetchone(), ("test_" + BASE, "wave7_synthetic"))
                cursor.execute("SELECT count(*) FROM intake_workflow_intakeitem")
                before = cursor.fetchone()[0]

            def forbid_sql(execute, sql, params, many, context):
                raise AssertionError("Read-only synthetic composition attempted database access")

            with connection.execute_wrapper(forbid_sql):
                decision = inspect_request(
                    case_key="batch-synthetic-csv-1",
                    actor="MUFTI",
                    action="synthetic::answer.create",
                    resource="synthetic::answer",
                )
            self.assertEqual(decision.synthetic_context, "VERIFIED")
            self.assertEqual(decision.effect, "DENY")
            self.assertIs(decision.allowed, False)
            self.assertEqual(decision.persisted_case_connection, "NOT_CONNECTED")
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM intake_workflow_intakeitem")
                self.assertEqual(cursor.fetchone()[0], before)
