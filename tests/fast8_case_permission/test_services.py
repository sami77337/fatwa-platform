"""Adversarial identity binding, exercising the existing queue and policy engines."""

import importlib
import json
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from hashlib import sha256
from unittest.mock import patch

from apps.editorial_queue import services as queue
from apps.permission_lab.sources import SourceUnavailable
from apps.policy_gap_engine import services as gap


class CasePermissionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.service = importlib.import_module("apps.fast8_case_permission.services")
        except ModuleNotFoundError:
            self.fail("The case-scoped permission adapter is absent")

    def describe(self, key="batch-synthetic-csv-1", resource="synthetic::answer"):
        return self.service.describe_case(key, scenario_resource=resource)

    def decide(self, descriptor=None, key="batch-synthetic-csv-1", **changes):
        result = self.service.evaluate_case(
            case_key=key,
            descriptor=descriptor if descriptor is not None else self.describe(),
            actor=changes.get("actor", "MUFTI"),
            action=changes.get("action", "synthetic::answer.create"),
            target_state=changes.get("target_state"),
        )
        self.assertEqual(result.effect, "DENY")
        self.assertIs(result.allowed, False)
        self.assertEqual(result.policy_status, "POLICY_PENDING")
        self.assertEqual(result.evidence_status, "MISSING_EVIDENCE")
        return result

    def test_descriptor_preserves_exact_queue_identity_without_mutable_content(self):
        descriptor = self.describe()
        row = queue.select_queue(queue.build_queue(), key=descriptor.case_key).selected
        self.assertEqual(descriptor.batch_id, "synthetic-csv")
        self.assertEqual(descriptor.row_ordinal, 1)
        self.assertEqual(descriptor.external_id, "SYN-CSV-1")
        self.assertEqual(descriptor.source_kind, "PARSED_FIELDS_SERIALIZATION")
        self.assertEqual(descriptor.source_sha256, sha256(row.case.raw_source.encode()).hexdigest())
        self.assertEqual(descriptor.payload_sha256, row.case.payload_sha256)
        self.assertTrue(all(type(v) in (str, int, type(None)) for v in asdict(descriptor).values()))
        with self.assertRaises(FrozenInstanceError):
            descriptor.case_key = "history"
        with self.assertRaises(FrozenInstanceError):
            self.decide().allowed = True

    def test_exact_descriptor_reuses_candidate_evaluation_without_grant(self):
        result = self.decide()
        expected = gap.evaluate(
            gap.CandidateRequest("MUFTI", "synthetic::answer.create", "synthetic::answer")
        )
        self.assertEqual(result.context_status, "VERIFIED")
        self.assertEqual(result.candidate_status, expected.candidate_status)
        self.assertTrue(result.valid_combination)
        self.assertTrue(set(expected.reason_codes) <= set(result.reason_codes))
        self.assertIn("MISSING_EVIDENCE", result.reason_codes)
        self.assertIsNotNone(result.descriptor)

    def test_original_byte_slice_and_history_serialization_are_not_conflated(self):
        intake = self.describe("intake-7")
        history = self.describe("history")
        self.assertEqual(intake.source_kind, "ORIGINAL_UTF8_SLICE")
        self.assertEqual(intake.row_ordinal, 7)
        self.assertIsInstance(intake.source_start, int)
        self.assertGreater(intake.source_end, intake.source_start)
        self.assertEqual(history.source_kind, "SERIALIZED_HISTORY_INTAKE")
        self.assertIsNone(history.row_ordinal)
        self.assertIsNone(history.source_start)
        self.assertNotEqual(intake.payload_sha256, intake.source_sha256)
        self.assertEqual(history.payload_sha256, history.source_sha256)

    def test_duplicate_external_ids_are_rejected_within_and_across_batches(self):
        for key in ("intake-1", "intake-4", "batch-synthetic-csv-2", "batch-synthetic-json-1"):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(self.service.ContextError, "DUPLICATE_EXTERNAL_ID"),
            ):
                self.describe(key)

    def test_exact_key_has_no_external_id_alias_or_normalization(self):
        for key in (
            "SYN-CSV-1",
            "batch-synthetic-csv-1 ",
            "batch-synthetic-csv-1\u200b",
            "../history",
            "HISTORY",
            None,
            [],
            True,
        ):
            with self.subTest(key=key), self.assertRaises(self.service.ContextError):
                self.describe(key)

    def test_descriptor_from_another_case_cannot_be_substituted(self):
        result = self.decide(self.describe("history"))
        self.assertEqual(result.context_status, "REJECTED")
        self.assertIn("CROSS_CASE_SUBSTITUTION", result.reason_codes)
        self.assertIsNone(result.descriptor)

    def test_each_identity_field_is_checked_against_current_row(self):
        descriptor = self.describe()
        mutations = {
            "batch_id": "synthetic-json",
            "external_id": "SYN-OTHER",
            "payload_sha256": "0" * 64,
            "source_sha256": "0" * 64,
            "row_sha256": "0" * 64,
            "source_kind": "ORIGINAL_UTF8_SLICE",
            "source_start": 0,
            "source_end": 5,
            "row_ordinal": 2,
            "fixture_label": "invented",
            "schema_version": "owner-approved",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                result = self.decide(replace(descriptor, **{field: value}))
                self.assertEqual(result.context_status, "REJECTED")
                self.assertFalse(result.valid_combination)

    def test_stale_row_detects_revision_change_with_same_intake(self):
        descriptor = self.describe("history")
        catalog = queue.build_queue_catalog()
        row = catalog.rows[0]
        changed = replace(row.case, status="ready")
        stale = replace(catalog, rows=(replace(row, case=changed), *catalog.rows[1:]))
        with patch.object(queue, "build_queue_catalog", return_value=stale):
            result = self.decide(descriptor, key="history")
        self.assertIn("STALE_DESCRIPTOR", result.reason_codes)
        self.assertEqual(result.context_status, "REJECTED")

    def test_nested_revision_tampering_is_detected_without_modifying_intake(self):
        descriptor = self.describe("history")
        catalog = queue.build_queue_catalog()
        row = catalog.rows[0]
        changed = replace(row.case, references=({"injected": "synthetic"},))
        stale = replace(catalog, rows=(replace(row, case=changed), *catalog.rows[1:]))
        with patch.object(queue, "build_queue_catalog", return_value=stale):
            result = self.decide(descriptor, key="history")
        self.assertIn("STALE_DESCRIPTOR", result.reason_codes)

    def test_unavailable_queue_is_not_connected_and_leaks_no_exception(self):
        descriptor = self.describe()
        with patch.object(
            queue, "build_queue_catalog", side_effect=queue.WorkbenchDataError("private detail")
        ):
            result = self.decide(descriptor)
        self.assertEqual(result.context_status, "NOT_CONNECTED")
        self.assertIn("QUEUE_UNAVAILABLE", result.reason_codes)
        self.assertNotIn("private detail", repr(result))

    def test_missing_policy_contract_is_not_a_verified_evaluation(self):
        descriptor = self.describe()
        with patch(
            "apps.permission_lab.sources.load_inventory",
            side_effect=SourceUnavailable("private detail"),
        ):
            result = self.decide(descriptor)
        self.assertEqual(result.context_status, "NOT_CONNECTED")
        self.assertIn("SOURCE_CONTRACT_UNAVAILABLE", result.reason_codes)
        self.assertFalse(result.valid_combination)

    def test_expected_payload_digest_must_match_actual_batch_bytes(self):
        catalog = queue.build_queue_catalog()
        original = self.describe()
        batch = catalog.batches[1]
        tampered = replace(
            batch,
            source=replace(batch.source, raw_source=batch.source.raw_source.replace("\r\n", "\n")),
        )
        with patch.object(
            queue,
            "build_queue_catalog",
            return_value=replace(
                catalog, batches=(catalog.batches[0], tampered, *catalog.batches[2:])
            ),
        ):
            result = self.decide(original)
        self.assertIn("PAYLOAD_SHA_MISMATCH", result.reason_codes)
        self.assertEqual(result.context_status, "REJECTED")

    def test_corrupt_row_digest_or_payload_or_batch_identity_is_rejected(self):
        catalog = queue.build_queue_catalog()
        original = self.describe()
        index = next(i for i, row in enumerate(catalog.rows) if row.case.key == original.case_key)
        row = catalog.rows[index]
        for changed in (
            replace(row, source_sha256="0" * 64),
            replace(row, case=replace(row.case, payload_sha256="0" * 64)),
            replace(row, batch_id="original"),
        ):
            rows = (*catalog.rows[:index], changed, *catalog.rows[index + 1 :])
            with (
                self.subTest(changed=changed.batch_id),
                patch.object(
                    queue, "build_queue_catalog", return_value=replace(catalog, rows=rows)
                ),
            ):
                self.assertEqual(self.decide(original).context_status, "REJECTED")

    def test_invalid_descriptor_types_do_not_coerce_or_echo_input(self):
        for value in (None, {}, [], "private marker", True):
            result = self.service.evaluate_case(
                case_key="history", descriptor=value, actor="MUFTI", action="P00-03::case.project"
            )
            self.assertEqual(result.context_status, "REJECTED")
            self.assertIs(result.allowed, False)
            self.assertNotIn("private marker", repr(result))

    def test_hypothetical_roles_and_invalid_actions_never_escalate(self):
        for actor, action, expected in (
            ("ORGANIZER_ADMIN", "synthetic::answer.create", "SCHOLARLY_AUTHORITY_RESTRICTED"),
            ("ORGANIZER", "synthetic::answer.create", "ACTOR_NOT_CANDIDATE"),
            ("DOMAIN_TRANSACTION", "synthetic::answer.create", "INTERNAL_PRINCIPAL_FORBIDDEN"),
            ("*", "synthetic::answer.create", "INVALID_IDENTIFIER"),
            ("MUFTI", "approve", "UNKNOWN_ACTION"),
        ):
            with self.subTest(actor=actor):
                self.assertIn(expected, self.decide(actor=actor, action=action).reason_codes)

    def test_workflow_context_is_explicit_hypothesis_never_derived_from_queue_status(self):
        descriptor = self.describe(resource="workflow::UNREVIEWED")
        result = self.decide(descriptor, action="start_review", target_state="IN_REVIEW")
        self.assertEqual(result.candidate_status, "EVIDENCE_MISSING")
        self.assertIn("WORKFLOW_NOT_AUTHORIZATION", result.reason_codes)
        self.assertEqual(result.workflow_target, "IN_REVIEW")
        mismatch = self.decide(descriptor, action="start_review", target_state="PUBLISHED")
        self.assertIn("TRANSITION_TARGET_MISMATCH", mismatch.reason_codes)

    def test_descriptor_json_roundtrip_rejects_unknown_fields_duplicates_and_boolean_ordinals(self):
        descriptor = self.describe()
        text = json.dumps(asdict(descriptor), ensure_ascii=False)
        self.assertEqual(self.service.parse_descriptor(text), descriptor)
        for invalid in (
            text[:-1] + ', "allowed": true}',
            text[:-1] + ', "case_key": "history"}',
            text.replace('"row_ordinal": 1', '"row_ordinal": true'),
            "[]",
            "x" * 8193,
        ):
            with self.subTest(invalid=invalid[:30]), self.assertRaises(self.service.ContextError):
                self.service.parse_descriptor(invalid)

    def test_repeated_reports_do_not_mutate_original_unicode_or_history(self):
        before = asdict(queue.build_queue_catalog())
        first = self.decide()
        second = self.decide()
        self.assertEqual(first, second)
        self.assertEqual(asdict(queue.build_queue_catalog()), before)
        row = queue.select_queue(queue.build_queue(), key="batch-synthetic-csv-1").selected
        self.assertEqual(row.case.question, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")
