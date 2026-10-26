"""Real Wave7 DTO/presentation contracts with mocked I/O, never PG evidence."""

import os
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings

from apps.fast9_pg_workflow_audit import adapter as a
from apps.intake_workflow import contracts as c
from apps.intake_workflow import guards, review


def sample():
    instant = datetime(2026, 10, 27, 8, 12, 13, 456789, tzinfo=timezone.utc)
    event = review.StoredReviewEvent(
        UUID(int=3),
        UUID(int=4),
        "start_review",
        "UNREVIEWED",
        "IN_REVIEW",
        "سببٌ اصطناعي\r\nفقط",
        instant,
    )
    raw = '{\r\n"question": "سؤالٌ اصطناعي"\r\n}'
    row = review.StoredReviewRow(
        UUID(int=2),
        UUID(int=1),
        1,
        "SYN-DUPLICATED",
        "سؤالٌ اصطناعي",
        raw,
        20,
        20 + len(raw.encode("utf-8")),
        "READY_FOR_EDITOR",
        "IN_REVIEW",
        None,
        (),
        (event,),
    )
    stored = review.ReviewWorklist(
        (review.ReviewBatchOption(UUID(int=1), instant),),
        UUID(int=1),
        (row,),
        row,
        1,
        1,
        1,
        1,
        1,
        "",
        "normalized",
        "",
        "",
    )
    identity = a.StoredIdentity(
        "test_wave7_synthetic_fast9",
        10001,
        row.batch_id,
        row.id,
        1,
        "a" * 64,
        sha256(raw.encode("utf-8")).hexdigest(),
        event.id,
        event.operation_id,
        a.window_sha256(stored),
    )
    return stored, identity


class AdapterTests(SimpleTestCase):
    def setUp(self):
        self.stored, self.identity = sample()
        self.gate = self.enterContext(
            patch("apps.reference.services._workflow_reads_enabled", return_value=True)
        )
        self.database = self.enterContext(patch.object(a, "_require_database"))
        self.source = self.enterContext(patch.object(a, "_source_sha", return_value="a" * 64))
        self.reader = self.enterContext(
            patch.object(review, "load_review_worklist", return_value=self.stored)
        )

    def read(self, **kwargs):
        return a.read_stored_audit(self.identity, synthetic_fixtures_only=True, **kwargs)

    def test_real_dto_composition_preserves_unicode_crlf_timestamps_and_unknown_joins(self):
        result = self.read()
        self.assertEqual(result.status, "CONNECTED")
        self.assertIs(result.provenance.selected_row, self.stored.row)
        self.assertEqual(
            result.provenance.chronology[-1].entry.timestamp, "2026-10-27T08:12:13.456789+00:00"
        )
        self.assertIn("\r\n", result.provenance.selected_row.original_row)
        self.assertEqual(result.audit_sha256, self.identity.audit_sha256)
        self.assertFalse(result.provenance.complete_history)
        self.assertEqual(result.revision_connection, "NOT_CONNECTED")
        self.assertEqual(result.permission_connection, "NOT_CONNECTED")
        self.assertEqual(result.owner_acceptance, "NOT_RUN")
        self.assertEqual(self.reader.call_count, 2)
        self.reader.assert_called_with(
            batch_id=self.identity.batch_id,
            row_id=self.identity.row_id,
            page=1,
            page_size=1,
            synthetic_fixtures_only=True,
        )

    def test_disabled_gate_precedes_any_database_work(self):
        self.gate.return_value = False
        self.assertEqual(self.read().reason, "READ_GATE_DISABLED")
        self.database.assert_not_called()
        self.source.assert_not_called()
        self.reader.assert_not_called()

    def test_ack_missing_identity_and_revision_link_fail_without_read(self):
        self.assertEqual(a.read_stored_audit(self.identity).status, "NOT_RUN")
        self.assertEqual(a.read_stored_audit(synthetic_fixtures_only=True).status, "NOT_CONNECTED")
        self.assertEqual(self.read(draft_revision=1).reason, "EXACT_REVISION_LINK_UNAVAILABLE")
        self.database.assert_not_called()
        self.reader.assert_not_called()

    def test_cross_batch_row_and_duplicate_external_id_do_not_join(self):
        for field, value in (("batch_id", UUID(int=9)), ("id", UUID(int=9)), ("row_ordinal", 2)):
            row = replace(self.stored.row, **{field: value})
            changed = replace(self.stored, row=row, rows=(row,))
            if field == "batch_id":
                changed = replace(
                    changed, batch_id=value, batches=(replace(changed.batches[0], id=value),)
                )
            self.reader.return_value = changed
            with self.subTest(field=field):
                result = self.read()
                self.assertEqual(result.reason, "ROW_IDENTITY_MISMATCH")
                self.assertIsNone(result.provenance)

    def test_stale_pins_reject_exact_source_row_event_operation_and_window(self):
        cases = (
            ("payload_sha256", "b" * 64, "SOURCE_IDENTITY_MISMATCH"),
            ("row_sha256", "b" * 64, "ROW_SOURCE_MISMATCH"),
            ("latest_event_id", UUID(int=9), "STALE_REVIEW_IDENTITY"),
            ("latest_operation_id", UUID(int=9), "STALE_REVIEW_IDENTITY"),
            ("audit_sha256", "b" * 64, "STALE_AUDIT_WINDOW"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                result = a.read_stored_audit(
                    replace(self.identity, **{field: value}), synthetic_fixtures_only=True
                )
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.provenance)

    def test_missing_selected_state_or_saved_events_never_fabricates_history(self):
        for stored, reason in (
            (replace(self.stored, row=None), "STORED_STATE_MISSING"),
            (
                replace(self.stored, row=replace(self.stored.row, events=())),
                "STORED_REVIEW_MISSING",
            ),
        ):
            self.reader.return_value = stored
            result = self.read()
            self.assertEqual(result.reason, reason)
            self.assertIsNone(result.provenance)

    def test_status_and_byte_span_mismatch_fail_closed(self):
        for changes, reason in (
            ({"review_status": "UNREVIEWED"}, "STALE_REVIEW_STATUS"),
            ({"source_byte_end": 99999}, "ROW_SOURCE_MISMATCH"),
        ):
            self.reader.return_value = replace(self.stored, row=replace(self.stored.row, **changes))
            self.assertEqual(self.read().reason, reason)

    def test_changed_second_observation_rejects_stale_result(self):
        changed = replace(self.stored.row.events[0], reason="تغييرٌ اصطناعي")
        self.reader.side_effect = [
            self.stored,
            replace(self.stored, row=replace(self.stored.row, events=(changed,))),
        ]
        self.assertEqual(self.read().reason, "STALE_AUDIT_WINDOW")

    def test_errors_redact_database_paths_sql_and_payloads(self):
        for error in (
            DatabaseError("password=SECRET"),
            RuntimeError("private/path"),
            guards.SyntheticWriteDenied("untrusted detail"),
            c.ContractError("private source text"),
        ):
            with self.subTest(kind=type(error).__name__):
                self.reader.side_effect = error
                result = self.read()
                self.assertEqual(result.status, "NOT_RUN")
                self.assertEqual(result.reason, "READ_UNAVAILABLE")
                self.assertIsNone(result.provenance)

    def test_reader_not_found_has_fixed_reason(self):
        self.reader.side_effect = review.ReviewNotFound("sensitive")
        self.assertEqual(self.read().reason, "STORED_STATE_MISSING")

    def test_bounded_history_and_malformed_dto_rejected(self):
        for row in (
            replace(self.stored.row, events=self.stored.row.events * 101),
            replace(self.stored.row, events=self.stored.row.events * 2),
            replace(self.stored.row, events_truncated=1),
        ):
            self.reader.return_value = replace(self.stored, row=row)
            self.assertEqual(self.read().status, "NOT_RUN")

    def test_truncation_is_preserved_never_complete_history(self):
        self.stored = replace(self.stored, row=replace(self.stored.row, events_truncated=True))
        self.reader.return_value = self.stored
        self.identity = replace(self.identity, audit_sha256=a.window_sha256(self.stored))
        result = self.read()
        self.assertTrue(result.provenance.events_truncated)
        self.assertFalse(result.provenance.complete_history)

    def test_unrelated_page_row_is_not_exposed_or_part_of_selected_pin(self):
        other = replace(self.stored.row, id=UUID(int=88), question="unrelated")
        self.reader.return_value = replace(self.stored, rows=(other,))
        result = self.read()
        self.assertEqual(result.status, "CONNECTED")
        self.assertEqual(result.provenance.worklist.rows, (self.stored.row,))
        self.assertNotIn("unrelated", repr(result))

    def test_invalid_identity_rejected_before_gate_or_db(self):
        for field, value in (
            ("database_name", "wave7_synthetic_fast9"),
            ("database_oid", True),
            ("database_oid", 0),
            ("row_id", str(self.identity.row_id)),
            ("row_ordinal", True),
            ("audit_sha256", "A" * 64),
            ("row_sha256", "x" * 65),
        ):
            with self.subTest(field=field):
                result = a.read_stored_audit(
                    replace(self.identity, **{field: value}), synthetic_fixtures_only=True
                )
                self.assertEqual(result.status, "NOT_CONNECTED")
        self.gate.assert_not_called()
        self.database.assert_not_called()


class DatabaseGuardTests(SimpleTestCase):
    def setUp(self):
        _, self.identity = sample()
        self.target = guards.DatabaseTarget(
            "default",
            self.identity.database_name,
            "wave7_synthetic_fast9",
            self.identity.database_name,
        )
        self.validate = self.enterContext(
            patch.object(guards, "validate_write_configuration", return_value=self.target)
        )
        self.connection = MagicMock(in_atomic_block=False)
        self.connection.get_autocommit.return_value = True
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (
            self.identity.database_name,
            c.DATABASE_ROLE,
            self.identity.database_oid,
            "on",
        )
        self.enterContext(patch.object(a, "connections", {"default": self.connection}))
        self.guard = self.enterContext(patch("apps.reference.services._require_workflow_read"))
        self.enterContext(override_settings(WAVE7_TEST_DATABASE_NAME=self.identity.database_name))

    def test_explicit_test_identity_and_read_only_required_before_wave7_guard(self):
        a._require_database(self.identity)
        self.guard.assert_called_once_with(synthetic_fixtures_only=True)
        sql = self.cursor.execute.call_args.args[0]
        self.assertTrue(sql.startswith("SELECT "))
        self.assertNotIn("set_config", sql)

    def test_base_database_never_opens_connection(self):
        self.validate.return_value = replace(self.target, database_name=self.target.base_name)
        with self.assertRaisesRegex(a.BoundaryDenied, "DATABASE_IDENTITY_MISMATCH"):
            a._require_database(self.identity)
        self.connection.cursor.assert_not_called()

    def test_actual_name_oid_role_and_read_only_must_match(self):
        correct = self.cursor.fetchone.return_value
        for index, value in ((0, "another"), (1, "postgres"), (2, 98765), (3, "off")):
            changed = list(correct)
            changed[index] = value
            self.cursor.fetchone.return_value = tuple(changed)
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(a.BoundaryDenied, "DATABASE_IDENTITY_OR_READ_ONLY_MISMATCH"),
            ):
                a._require_database(self.identity)
        self.guard.assert_not_called()

    def test_open_transaction_rejected(self):
        self.connection.in_atomic_block = True
        with self.assertRaisesRegex(a.BoundaryDenied, "AUTOCOMMIT_REQUIRED"):
            a._require_database(self.identity)
        self.connection.cursor.assert_not_called()


class RealDisabledGateTests(SimpleTestCase):
    @override_settings(WAVE7_READS_ENABLED=False)
    def test_real_wave7_gate_never_accesses_database(self):
        _, identity = sample()
        with patch.dict(os.environ, {"FATWA_WAVE7_SYNTHETIC_READS": "0"}):
            self.assertEqual(
                a.read_stored_audit(identity, synthetic_fixtures_only=True).reason,
                "READ_GATE_DISABLED",
            )

    def test_real_configuration_guard_denies_without_write_flag(self):
        _, identity = sample()
        with patch.dict(os.environ, {"FATWA_WAVE7_SYNTHETIC_WRITES": "0"}):
            with self.assertRaisesRegex(guards.SyntheticWriteDenied, "WRITES_DISABLED"):
                a._require_database(identity)


class SourceQueryTests(SimpleTestCase):
    def test_source_lookup_is_bound_to_checked_alias_despite_database_router(self):
        _, identity = sample()
        model = MagicMock()
        query = model.objects.using.return_value.filter.return_value
        query.values_list.return_value.first.return_value = identity.payload_sha256
        with patch.dict(
            "sys.modules", {"apps.intake_workflow.models": SimpleNamespace(IntakeBatch=model)}
        ):
            self.assertEqual(a._source_sha(identity), identity.payload_sha256)
        model.objects.using.assert_called_once_with("default")
        model.objects.filter.assert_not_called()
        model.objects.using.return_value.filter.assert_called_once_with(
            pk=identity.batch_id,
            scope=c.SYNTHETIC_SCOPE,
            source_config_id=c.SOURCE_CONFIG_ID,
            contract_version=c.CONTRACT_VERSION,
        )
