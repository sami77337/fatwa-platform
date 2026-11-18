"""SEC13-01 target failure must never publish READY or delete unknown identity."""

import json
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from psycopg import sql

from apps.platform_recovery import maintenance, service
from tests.casework import test_v11_maintenance as fixtures


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
)
class SchemaQuarantineTests(TransactionTestCase):
    setUp = fixtures.MaintenanceIntegrationTests.setUp
    freeze = fixtures.MaintenanceIntegrationTests.freeze
    capture = fixtures.MaintenanceIntegrationTests.capture

    def drill(self, *, unknown_identity):
        original = "(ARRAY['::character varying])::text[]"
        altered = "ARRAY[('::character varying)::text]"
        with connection.cursor() as db:
            db.execute("CREATE TABLE v13_quarantine_literal (marker text)")
            db.execute(
                "CREATE UNIQUE INDEX v13_quarantine_index ON v13_quarantine_literal(marker) "
                "WHERE marker <> %s",
                [original],
            )
        events, targets = [], []
        journal = service.journal

        def observe(target, state):
            events.append(state["state"])
            return journal(target, state)

        def tamper(stage):
            if stage != "schema_restored":
                return
            target = max(self.root.glob("restore-*"), key=lambda path: path.stat().st_mtime_ns)
            state = json.loads((target / "journal.json").read_text())
            with service.connect(state["database"]) as db:
                db.execute("DROP INDEX public.v13_quarantine_index")
                db.execute(
                    sql.SQL(
                        "CREATE UNIQUE INDEX v13_quarantine_index ON public.v13_quarantine_literal(marker) "
                        "WHERE marker <> {}"
                    ).format(sql.Literal(altered))
                )
            if unknown_identity:
                with service.connect() as db:
                    db.execute(
                        sql.SQL("COMMENT ON DATABASE {} IS 'unknown-target-identity'").format(
                            sql.Identifier(state["database"])
                        )
                    )
            targets.append((target, state))

        try:
            expected = (
                "restore_failed_rollback_pending"
                if unknown_identity
                else "restored_schema_mismatch"
            )
            with (
                patch.object(service, "journal", side_effect=observe),
                patch.object(service, "checkpoint", side_effect=tamper),
                self.assertRaisesRegex(service.RecoveryError, expected),
            ):
                fixtures.MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(
                    self
                )
            self.assertEqual(len(targets), 1, "the actual target predicate must be changed")
            self.assertNotIn("READY", events)
            target, identity = targets[0]
            state = json.loads((target / "journal.json").read_text())
            self.assertEqual(state["failure_code"], "restored_schema_mismatch")
            self.assertEqual(
                state["state"], "FAILED" if unknown_identity else "ROLLED_BACK_FILES_PRESERVED"
            )
            self.assertTrue(
                any(
                    path.read_bytes() == self.media.raw
                    for path in (target / "private" / "objects").glob("*.blob")
                )
            )
            self.assertEqual(maintenance.status(root=self.control)["phase"], "FROZEN")
            with service.connect() as db:
                present = db.execute(
                    "SELECT count(*) FROM pg_database WHERE datname=%s", [identity["database"]]
                ).fetchone()[0]
            self.assertEqual(present, int(unknown_identity))
            if unknown_identity:
                with self.assertRaisesRegex(service.RecoveryError, "rollback_identity_mismatch"):
                    service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
                with service.connect() as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT count(*) FROM pg_database WHERE datname=%s",
                            [identity["database"]],
                        ).fetchone()[0],
                        1,
                    )
        finally:
            with connection.cursor() as db:
                db.execute("DROP TABLE v13_quarantine_literal")
        # The unknown database is deliberately left to the owned disposable
        # cluster's teardown; the recovery application must not guess deletion.

    def test_changed_predicate_is_quarantined_before_ready_with_assets_preserved(self):
        self.drill(unknown_identity=False)

    def test_changed_predicate_with_unproven_identity_preserves_target_for_manual_review(self):
        self.drill(unknown_identity=True)
