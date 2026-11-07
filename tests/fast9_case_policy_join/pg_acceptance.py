"""Opt-in only: not auto-collected by offline test discovery; never skip/xfail."""

import json
from hashlib import sha256

from django.db import connection, transaction
from django.test import SimpleTestCase

from apps.fast9_case_policy_join.services import inspect_request
from apps.intake_workflow.fixtures import synthetic_payload
from apps.intake_workflow.guards import require_synthetic_write
from apps.intake_workflow.intake import import_intake
from tools.fast9_case_policy_join.postgres_check import BASE


class SyntheticNonMutationAcceptance(SimpleTestCase):
    databases = {"default"}

    def test_composition_uses_no_database_and_keeps_owned_synthetic_rows_unchanged(self):
        context = require_synthetic_write(synthetic_fixtures_only=True)
        self.assertEqual(context.database_name, "test_" + BASE)
        fixture = import_intake(
            synthetic_payload(), idempotency_key="policy-nonmutation", synthetic_fixtures_only=True
        )
        self.assertEqual(fixture.item_count, 8)

        def snapshot():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*), jsonb_agg(to_jsonb(item) ORDER BY item.id)::text "
                    "FROM intake_workflow_intakeitem AS item"
                )
                count, rows = cursor.fetchone()
            return count, sha256(rows.encode("utf-8")).hexdigest()

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone()[0], "on")
                cursor.execute("SELECT current_database(), current_user")
                self.assertEqual(cursor.fetchone(), ("test_" + BASE, "wave7_synthetic"))
            before = snapshot()
            self.assertEqual(before[0], fixture.item_count)

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
            after = snapshot()
            self.assertEqual(after, before)
            print(
                "FAST9_POLICY "
                + json.dumps(
                    {
                        "database": context.database_name,
                        "oid": context.database_oid,
                        "intake_rows_before": before[0],
                        "intake_rows_after": after[0],
                        "intake_sha256_before": before[1],
                        "intake_sha256_after": after[1],
                        "fixture_sha256": fixture.payload_sha256,
                        "effect": decision.effect,
                        "allowed": decision.allowed,
                        "persisted_case_connection": decision.persisted_case_connection,
                        "transaction_read_only": True,
                    },
                    sort_keys=True,
                )
            )
