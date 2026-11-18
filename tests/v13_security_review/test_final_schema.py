"""Independent real-pg_dump checks: data literals are not SQL expressions."""

import json
import os
from hashlib import sha256
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from psycopg import sql

from apps.platform_recovery import service
from tests.casework import test_v11_maintenance as restore_fixtures


class SchemaLiteralReviewTests(TransactionTestCase):
    def test_partial_index_string_value_change_must_change_recovery_fingerprint(self):
        # Both are ordinary text data values; neither is an SQL array expression.
        original_value = "(ARRAY['::character varying])::text[]"
        altered_value = "ARRAY[('::character varying)::text]"
        tools = service.PostgresTools(os.environ["V12_PG_BIN"])
        database = connection.settings_dict["NAME"]
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE v13_review_literals (marker text)")
        try:
            schemas, memberships, permits_duplicates = [], [], []
            for value in (original_value, altered_value):
                with connection.cursor() as cursor:
                    cursor.execute("DROP INDEX IF EXISTS v13_review_literal_index")
                    cursor.execute("DELETE FROM v13_review_literals")
                    cursor.execute(
                        "CREATE UNIQUE INDEX v13_review_literal_index ON v13_review_literals(marker) "
                        "WHERE marker <> %s",
                        [value],
                    )
                    cursor.execute("SELECT %s <> %s", [original_value, value])
                    memberships.append(cursor.fetchone()[0])
                try:
                    with transaction.atomic(), connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO v13_review_literals VALUES (%s), (%s)",
                            [original_value, original_value],
                        )
                    permits_duplicates.append(True)
                except IntegrityError:
                    permits_duplicates.append(False)
                raw = tools.run("pg_dump", database, "--schema-only").decode()
                schemas.append((raw, service.canonical_schema(raw)))
            self.assertEqual(memberships, [False, True])
            self.assertEqual(permits_duplicates, [True, False])
            self.assertNotEqual(schemas[0][0], schemas[1][0])
            self.assertNotEqual(
                sha256(schemas[0][1]).hexdigest(),
                sha256(schemas[1][1]).hexdigest(),
                "Different real index predicates collapsed to the same recovery schema",
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE v13_review_literals")


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
)
class EncryptedSchemaReview(TransactionTestCase):
    setUp = restore_fixtures.MaintenanceIntegrationTests.setUp
    freeze = restore_fixtures.MaintenanceIntegrationTests.freeze
    capture = restore_fixtures.MaintenanceIntegrationTests.capture

    def test_changed_quoted_index_predicate_on_restored_target_is_quarantined(self):
        original_value = "(ARRAY['::character varying])::text[]"
        altered_value = "ARRAY[('::character varying)::text]"
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE v13_review_literals (marker text)")
            cursor.execute(
                "CREATE UNIQUE INDEX v13_review_literal_index ON v13_review_literals(marker) WHERE marker <> %s",
                [original_value],
            )
        altered = []

        def alter_target(stage):
            if stage != "schema_restored":
                return
            records = sorted(
                self.root.glob("restore-*/journal.json"), key=lambda p: p.stat().st_mtime_ns
            )
            state = json.loads(records[-1].read_text())
            with service.connect(state["database"]) as db:
                db.execute("DROP INDEX public.v13_review_literal_index")
                db.execute(
                    sql.SQL(
                        "CREATE UNIQUE INDEX v13_review_literal_index ON public.v13_review_literals(marker) WHERE marker <> {}"
                    ).format(sql.Literal(altered_value))
                )
            altered.append(state["database"])

        try:
            with (
                patch.dict(os.environ, {"FATWA_TEST_PG_BIN": os.environ["V12_PG_BIN"]}),
                patch.object(service, "checkpoint", side_effect=alter_target),
            ):
                with self.assertRaisesRegex(service.RecoveryError, "restored_schema_mismatch"):
                    restore_fixtures.MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(
                        self
                    )
                    self.assertEqual(len(altered), 1, "target alteration checkpoint must execute")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE v13_review_literals")
