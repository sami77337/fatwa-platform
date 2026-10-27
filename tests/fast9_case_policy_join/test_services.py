"""Exercise real queue, FAST8 receipts and pinned policy services offline."""

import importlib
import json
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from unittest.mock import patch

from apps.editorial_queue import services as queue
from apps.fast8_case_permission import services as cases
from apps.permission_lab import services as lab
from apps.permission_lab.sources import SourceUnavailable
from apps.policy_gap_engine import evidence


class JoinTests(unittest.TestCase):
    def setUp(self):
        try:
            self.join = importlib.import_module("apps.fast9_case_policy_join.services")
        except ModuleNotFoundError:
            self.fail("Case/policy evidence selector is not implemented")

    def select(self, **changes):
        args = dict(
            case_key="batch-synthetic-csv-1",
            actor="MUFTI",
            action="synthetic::answer.create",
            resource="synthetic::answer",
        )
        return self.join.select_evidence(**(args | changes))

    def decide(self, receipt=None, **changes):
        args = dict(
            case_key="batch-synthetic-csv-1",
            actor="MUFTI",
            action="synthetic::answer.create",
            resource="synthetic::answer",
        )
        result = self.join.evaluate_join(receipt=receipt or self.select(), **(args | changes))
        self.assertEqual(result.effect, "DENY")
        self.assertIs(result.allowed, False)
        self.assertEqual(result.policy_status, "POLICY_PENDING")
        self.assertEqual(result.evidence_status, "MISSING_EVIDENCE")
        self.assertEqual(result.owner_policy_connection, "NOT_CONNECTED")
        self.assertEqual(result.persisted_case_connection, "NOT_CONNECTED")
        return result

    def test_exact_join_carries_source_row_and_policy_evidence_without_authorization(self):
        receipt = self.select()
        self.assertEqual(receipt.case.external_id, "SYN-CSV-1")
        self.assertEqual(receipt.case.row_ordinal, 1)
        self.assertEqual(receipt.scenario.action, "synthetic::answer.create")
        self.assertEqual(receipt.scenario.record_category, "actions")
        self.assertEqual(receipt.scenario.binding_scope, "SYNTHETIC_ID_MEMBERSHIP_ONLY")
        self.assertEqual(
            receipt.scenario.inventory_sha256,
            "40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4",
        )
        result = self.decide(receipt)
        self.assertEqual(result.synthetic_context, "VERIFIED")
        self.assertEqual(result.candidate_status, "CANDIDATE_ONLY")
        self.assertTrue(result.valid_combination)
        self.assertEqual(result.receipt, receipt)
        self.assertIn("POLICY_PENDING", result.reason_codes)
        self.assertIn("MISSING_EVIDENCE", result.reason_codes)

    def test_cross_case_and_cross_scenario_receipts_are_not_substitutable(self):
        for changes, code in (
            ({"case_key": "history"}, "CROSS_CASE_SUBSTITUTION"),
            ({"actor": "ORGANIZER_ADMIN"}, "SCENARIO_SUBSTITUTION"),
            ({"action": "synthetic::answer.draft"}, "SCENARIO_SUBSTITUTION"),
            ({"resource": "synthetic::catalog"}, "SCENARIO_SUBSTITUTION"),
            ({"target_state": "PUBLISHED"}, "SCENARIO_SUBSTITUTION"),
        ):
            with self.subTest(changes=changes):
                result = self.decide(**changes)
                self.assertEqual(result.synthetic_context, "REJECTED")
                self.assertIn(code, result.reason_codes)
                self.assertIsNone(result.receipt)

    def test_stale_case_and_policy_receipt_fields_are_rejected(self):
        receipt = self.select()
        for altered in (
            replace(receipt, case=replace(receipt.case, row_sha256="0" * 64)),
            replace(receipt, scenario=replace(receipt.scenario, evidence_sha256="0" * 64)),
            replace(receipt, scenario=replace(receipt.scenario, policy_token="APPROVED")),
        ):
            result = self.decide(altered)
            self.assertIn("STALE_RECEIPT", result.reason_codes)
            self.assertIsNone(result.receipt)

    def test_duplicate_ids_and_unicode_keys_do_not_get_normalized(self):
        for key in (
            "intake-1",
            "batch-synthetic-csv-2",
            "batch-synthetic-json-1",
            "history\u200b",
            "hıstory",
            " history",
            "../history",
            "HISTORY",
        ):
            with self.subTest(key=key), self.assertRaises(self.join.JoinError):
                self.select(case_key=key)

    def test_unknown_actor_action_resource_and_malicious_types_fail_closed(self):
        for field, value in (
            ("actor", "ROOT"),
            ("actor", "MUFTI\u200b"),
            ("actor", "DOMAIN_TRANSACTION"),
            ("action", "approve"),
            ("resource", "synthetic::unknown"),
            ("actor", []),
            ("actor", True),
            ("resource", "https://private.invalid"),
            ("action", "<script>secret</script>"),
            ("target_state", {}),
        ):
            with self.subTest(field=field, value=value):
                result = self.decide(**{field: value})
                self.assertEqual(result.synthetic_context, "REJECTED")
                self.assertFalse(result.valid_combination)
                self.assertNotIn("private.invalid", repr(result))
                self.assertNotIn("secret", repr(result))

    def test_workflow_probe_without_policy_record_stays_not_connected(self):
        with self.assertRaisesRegex(self.join.JoinError, "SCENARIO_EVIDENCE_MISSING"):
            self.select(action="start_review", resource="workflow::UNREVIEWED")

    def test_action_resource_mismatch_is_not_verified(self):
        with self.assertRaisesRegex(self.join.JoinError, "INVALID_SCENARIO"):
            self.select(resource="synthetic::catalog")

    def test_candidate_roles_and_disabled_transitions_remain_deny(self):
        for changes, code in (
            ({"actor": "ORGANIZER_ADMIN"}, "SCHOLARLY_AUTHORITY_RESTRICTED"),
            ({"actor": "ORGANIZER"}, "ACTOR_NOT_CANDIDATE"),
            (
                {"action": "synthetic::answer.draft", "target_state": "SYNTHETIC_REVIEW"},
                "TRANSITION_DISABLED",
            ),
        ):
            with self.subTest(changes=changes):
                receipt = self.select(**changes)
                result = self.decide(receipt, **changes)
                self.assertEqual(result.synthetic_context, "VERIFIED")
                self.assertIn(code, result.reason_codes)

    def test_policy_disappearance_after_evaluation_clears_receipt(self):
        receipt = self.select()
        original = cases.evaluate_case

        def disappearing(**kwargs):
            result = original(**kwargs)
            failure = patch.object(
                evidence, "load_evidence", side_effect=SourceUnavailable("secret")
            )
            failure.start()
            self.addCleanup(failure.stop)
            return result

        with patch.object(cases, "evaluate_case", side_effect=disappearing):
            result = self.decide(receipt)
        self.assertEqual(result.synthetic_context, "NOT_CONNECTED")
        self.assertIsNone(result.receipt)
        self.assertNotIn("secret", repr(result))

    def test_policy_identity_change_after_evaluation_is_detected(self):
        receipt = self.select()
        original = cases.evaluate_case
        inventory, report = evidence.load_evidence()
        changed = deepcopy(report)
        changed["records"][0]["source_ref"]["record_id"] = "synthetic::changed"

        def changing(**kwargs):
            result = original(**kwargs)
            mutation = patch.object(evidence, "load_evidence", return_value=(inventory, changed))
            mutation.start()
            self.addCleanup(mutation.stop)
            return result

        with patch.object(cases, "evaluate_case", side_effect=changing):
            result = self.decide(receipt)
        self.assertIn("STALE_RECEIPT", result.reason_codes)
        self.assertIsNone(result.receipt)

    def test_row_change_after_engine_returns_is_detected(self):
        receipt = self.select()
        original = cases.evaluate_case
        catalog = queue.build_queue_catalog()
        rows = tuple(
            replace(row, unresolved_count=row.unresolved_count + 1)
            if row.case.key == receipt.case.case_key
            else row
            for row in catalog.rows
        )

        def changing(**kwargs):
            result = original(**kwargs)
            mutation = patch.object(
                queue, "build_queue_catalog", return_value=replace(catalog, rows=rows)
            )
            mutation.start()
            self.addCleanup(mutation.stop)
            return result

        with patch.object(cases, "evaluate_case", side_effect=changing):
            result = self.decide(receipt)
        self.assertIn("STALE_RECEIPT", result.reason_codes)

    def test_duplicate_policy_record_and_catalog_ids_are_rejected(self):
        inventory, report = evidence.load_evidence()
        duplicate = deepcopy(report)
        duplicate["records"].append(deepcopy(duplicate["records"][0]))
        with patch.object(evidence, "load_evidence", return_value=(inventory, duplicate)):
            with self.assertRaisesRegex(self.join.JoinError, "DUPLICATE_POLICY_ID"):
                self.select()
        catalog = lab.build_catalog()
        with patch.object(
            lab,
            "build_catalog",
            return_value=replace(catalog, actors=(*catalog.actors, catalog.actors[0])),
        ):
            with self.assertRaisesRegex(self.join.JoinError, "DUPLICATE_SCENARIO_ID"):
                self.select()

    def test_json_receipt_rejects_nested_duplicates_extra_grants_and_excess_size(self):
        receipt = self.select()
        text = json.dumps(asdict(receipt), ensure_ascii=False)
        self.assertEqual(self.join.parse_receipt(text), receipt)
        for bad in (
            text[:-1] + ', "allowed": true}',
            text.replace('"actor": "MUFTI"', '"actor":"MUFTI","actor":"ORGANIZER"'),
            text.replace('"row_ordinal": 1', '"row_ordinal": true'),
            "[" * 2000,
            "x" * 16385,
            "\ud800",
            "null",
        ):
            with self.subTest(bad=bad[:20]), self.assertRaises(self.join.JoinError):
                self.join.parse_receipt(bad)

    def test_repeated_composition_preserves_unicode_crlf_and_all_queue_data(self):
        before = asdict(queue.build_queue_catalog())
        first = self.decide()
        self.assertEqual(first, self.decide())
        self.assertEqual(before, asdict(queue.build_queue_catalog()))
        row = queue.select_queue(queue.build_queue(), key=first.receipt.case.case_key).selected
        self.assertEqual(row.case.question, "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")

    def test_missing_queue_or_policy_never_returns_partial_evidence(self):
        receipt = self.select()
        for module, name, error in (
            (queue, "build_queue_catalog", queue.WorkbenchDataError("secret")),
            (evidence, "load_evidence", SourceUnavailable("secret")),
        ):
            with patch.object(module, name, side_effect=error):
                result = self.decide(receipt)
            self.assertEqual(result.synthetic_context, "NOT_CONNECTED")
            self.assertIsNone(result.receipt)
            self.assertNotIn("secret", repr(result))

    def test_invalid_receipt_cannot_carry_arbitrary_objects(self):
        for receipt in ({}, "secret", True):
            result = self.join.evaluate_join(
                case_key="history", receipt=receipt, actor="MUFTI", action="x", resource="x"
            )
            self.assertEqual(result.synthetic_context, "REJECTED")
            self.assertIsNone(result.receipt)
            self.assertIs(result.allowed, False)
