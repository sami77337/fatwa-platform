"""Explicit existing-state acceptance, never discovered as a fixture-seeding test.

Only invoked after the CLI's positive read of supplied state. No setup/teardown,
flush, migration, review transition or schema operation is permitted here.
"""

import os
import unittest
from dataclasses import replace
from uuid import UUID

from django.db import connections

from apps.fast9_pg_workflow_audit.adapter import StoredIdentity, read_stored_audit


def run_acceptance(identity: StoredIdentity) -> dict:
    class ExistingStateTests(unittest.TestCase):
        def read(self, value=identity, **kwargs):
            return read_stored_audit(value, synthetic_fixtures_only=True, **kwargs)

        def test_exact_supplied_state_and_queries(self):
            statements = []

            def readonly(execute, sql, params, many, context):
                self.assertTrue(sql.lstrip().upper().startswith("SELECT "))
                self.assertFalse(many)
                statements.append(True)
                return execute(sql, params, many, context)

            with connections["default"].execute_wrapper(readonly):
                result = self.read()
            self.assertEqual(result.status, "CONNECTED")
            self.assertEqual(result.audit_sha256, identity.audit_sha256)
            self.assertGreater(len(statements), 0)
            self.assertLess(len(statements), 120)
            self.assertEqual(result.provenance.selected_row.id, identity.row_id)
            self.assertFalse(result.provenance.complete_history)
            self.assertEqual(result.revision_connection, "NOT_CONNECTED")

        def test_wrong_database_oid(self):
            alternate = identity.database_oid % 4294967295 + 1
            self.assertEqual(
                self.read(replace(identity, database_oid=alternate)).reason,
                "DATABASE_IDENTITY_OR_READ_ONLY_MISMATCH",
            )

        def test_wrong_source_and_row_hash(self):
            for name, reason in (
                ("payload_sha256", "SOURCE_IDENTITY_MISMATCH"),
                ("row_sha256", "ROW_SOURCE_MISMATCH"),
            ):
                old = getattr(identity, name)
                changed = ("1" if old[0] == "0" else "0") + old[1:]
                self.assertEqual(self.read(replace(identity, **{name: changed})).reason, reason)

        def test_cross_case_row_selection(self):
            # No enumeration of other rows/cases. A supplied batch may never be
            # paired with an arbitrary row, even when the external ID duplicates.
            changed = UUID(int=identity.row_id.int ^ 1)
            result = self.read(replace(identity, row_id=changed))
            self.assertEqual(result.status, "NOT_CONNECTED")
            self.assertIsNone(result.provenance)

        def test_stale_event_and_audit(self):
            result = self.read(
                replace(identity, latest_event_id=UUID(int=identity.latest_event_id.int ^ 1))
            )
            self.assertEqual(result.reason, "STALE_REVIEW_IDENTITY")
            old = identity.audit_sha256
            changed = ("1" if old[0] == "0" else "0") + old[1:]
            self.assertEqual(
                self.read(replace(identity, audit_sha256=changed)).reason, "STALE_AUDIT_WINDOW"
            )

        def test_disabled_gate_has_no_sql(self):
            old = os.environ.get("FATWA_WAVE7_SYNTHETIC_READS")

            def forbidden(*args):
                raise AssertionError("disabled gate queried DB")

            try:
                os.environ["FATWA_WAVE7_SYNTHETIC_READS"] = "0"
                with connections["default"].execute_wrapper(forbidden):
                    self.assertEqual(self.read().reason, "READ_GATE_DISABLED")
            finally:
                if old is None:
                    os.environ.pop("FATWA_WAVE7_SYNTHETIC_READS", None)
                else:
                    os.environ["FATWA_WAVE7_SYNTHETIC_READS"] = old

        def test_exact_revision_link_never_inferred(self):
            self.assertEqual(self.read(draft_revision=1).reason, "EXACT_REVISION_LINK_UNAVAILABLE")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExistingStateTests)
    result = unittest.TestResult()
    suite.run(result)
    # Deliberately no assertion values, tracebacks, raw SQL, source or credentials.
    return {
        "status": "PASS"
        if result.wasSuccessful() and result.testsRun == 7 and not result.skipped
        else "FAIL",
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
