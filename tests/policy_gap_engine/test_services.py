"""Executable gap semantics, with no Django setup or database."""

import importlib
import json
import unittest
from dataclasses import FrozenInstanceError
from itertools import product
from unittest.mock import patch

from apps.permission_lab import services as lab
from apps.permission_lab.sources import SourceUnavailable


class GapServiceTests(unittest.TestCase):
    def service(self):
        try:
            return importlib.import_module("apps.policy_gap_engine.services")
        except ModuleNotFoundError:
            self.fail("The executable policy gap service is absent")

    def decision(
        self,
        actor="MUFTI",
        action="synthetic::answer.create",
        resource="synthetic::answer",
        target_state=None,
    ):
        service = self.service()
        result = service.evaluate(service.CandidateRequest(actor, action, resource, target_state))
        self.assertEqual(result.effect, "DENY")
        self.assertIs(result.allowed, False)
        self.assertEqual(result.reason_codes, tuple(sorted(set(result.reason_codes))))
        return result

    def test_candidate_is_distinct_from_authorization_and_missing_evidence(self):
        result = self.decision()
        self.assertEqual(result.candidate_status, "CANDIDATE_ONLY")
        self.assertTrue(result.valid_combination)
        self.assertTrue(
            {"DENY_DEFAULT", "POLICY_PENDING", "EVIDENCE_MISSING"} <= set(result.reason_codes)
        )
        with self.assertRaises(FrozenInstanceError):
            result.allowed = True

    def test_admin_peer_is_not_a_scholarly_candidate(self):
        result = self.decision(actor="ORGANIZER_ADMIN")
        self.assertEqual(result.candidate_status, "NOT_CANDIDATE")
        self.assertIn("SCHOLARLY_AUTHORITY_RESTRICTED", result.reason_codes)

    def test_workflow_compatibility_has_no_policy_mapping(self):
        result = self.decision(action="start_review", resource="workflow::UNREVIEWED")
        self.assertTrue(result.valid_combination)
        self.assertEqual(result.candidate_status, "EVIDENCE_MISSING")
        self.assertIn("REQUEST_POLICY_EVIDENCE_MISSING", result.reason_codes)
        self.assertIn("TRANSITION_UNAUTHORIZED", result.reason_codes)
        self.assertEqual(result.workflow_target, "IN_REVIEW")

    def test_targets_are_checked_but_no_transition_is_authorized(self):
        for target, valid, code in (
            ("SYNTHETIC_REVIEW", True, "TRANSITION_UNAUTHORIZED"),
            ("PUBLISHED", False, "TRANSITION_TARGET_MISMATCH"),
            ([], False, "INVALID_IDENTIFIER"),
            ("SYNTHETIC_REVIEW\u200b", False, "INVALID_IDENTIFIER"),
        ):
            with self.subTest(target=target):
                result = self.decision(action="synthetic::answer.draft", target_state=target)
                self.assertEqual(result.valid_combination, valid)
                self.assertIn(code, result.reason_codes)
        self.assertIn(
            "NOT_A_TRANSITION", self.decision(target_state="SYNTHETIC_REVIEW").reason_codes
        )

    def test_every_existing_triple_and_workflow_edge_stays_denied(self):
        catalog = lab.build_catalog()
        for actor, action, resource in product(catalog.actors, catalog.actions, catalog.resources):
            with self.subTest(actor=actor, action=action, resource=resource.id):
                self.decision(actor, action, resource.id)

    def test_untrusted_values_never_coerce_or_crash(self):
        for value in (None, True, 4, [], {}, "*", "MUFTI ", "ＭＵＦＴＩ", "x" * 97):
            for index in range(3):
                values = ["MUFTI", "synthetic::answer.create", "synthetic::answer"]
                values[index] = value
                with self.subTest(index=index, value=value):
                    result = self.decision(*values)
                    self.assertFalse(result.valid_combination)
                    self.assertEqual(result.candidate_status, "INVALID")

    def test_unavailable_source_becomes_explicit_denial_not_an_exception(self):
        with patch(
            "apps.permission_lab.sources.load_inventory",
            side_effect=SourceUnavailable("private path must not leak"),
        ):
            result = self.decision()
        self.assertIn("SOURCE_CONTRACT_UNAVAILABLE", result.reason_codes)
        self.assertEqual(result.candidate_status, "EVIDENCE_MISSING")

    def test_report_is_deterministic_and_preserves_original_arabic(self):
        service = self.service()
        first = service.canonical_json(service.build_report())
        self.assertEqual(first, service.canonical_json(service.build_report()))
        report = json.loads(first)
        self.assertEqual(report["status"], "SYNTHETIC_EVALUATED")
        self.assertEqual(report["effect"], "DENY")
        self.assertIs(report["allowed"], False)
        self.assertEqual(report["adversarial_checks"]["status"], "PASS")
        self.assertGreaterEqual(report["adversarial_checks"]["evaluated"], 15)
        self.assertIn(lab.build_catalog().resources[0].label, first)
        self.assertIn(
            lab.evaluate("MUFTI", "synthetic::answer.create", "synthetic::answer")
            .reasons[0]
            .message,
            first,
        )
        self.assertNotIn("\\u", first)

    def test_unknown_input_is_not_echoed_or_resolved_as_a_real_record(self):
        service = self.service()
        raw = "private-case-value"
        report = service.build_report((service.CandidateRequest("MUFTI", "approve", raw),))
        encoded = service.canonical_json(report)
        self.assertNotIn(raw, encoded)
        self.assertIn("UNKNOWN_RESOURCE", encoded)
        self.assertEqual(len(report["requests"]), 1)

    def test_report_does_not_hide_failure_as_successful_adversarial_run(self):
        service = self.service()
        from apps.permission_lab.upstream import validator

        # Only mutation checks are suppressed, not trusted fixture validation.
        original = validator.inspect_structure

        def suppress_attack(document, *, synthetic=False):
            if any(row.get("grant_effect") == "ALLOW" for row in document["actions"]):
                return []
            return original(document, synthetic=synthetic)

        with patch.object(validator, "inspect_structure", side_effect=suppress_attack):
            report = service.build_report()
        self.assertEqual(report["adversarial_checks"]["status"], "FAIL")
        self.assertGreater(report["adversarial_checks"]["failed"], 0)

    def test_service_envelopes_are_bounded_and_not_policy_inputs(self):
        service = self.service()
        request = service.CandidateRequest("MUFTI", "synthetic::answer.create", "synthetic::answer")
        with patch.object(service, "load_evidence", side_effect=AssertionError("must not read")):
            for value in ([], (), {}, (request,) * 257, (None,)):
                with self.subTest(value=type(value).__name__):
                    with self.assertRaisesRegex(ValueError, "INVALID_REQUEST_ENVELOPE"):
                        service.build_report(value)
        for value in (None, {}, (), "MUFTI"):
            result = service.evaluate(value)
            self.assertEqual(result.effect, "DENY")
            self.assertEqual(result.candidate_status, "INVALID")

    def test_offline_report_does_not_open_sockets(self):
        with patch("socket.socket", side_effect=AssertionError("offline service opened a socket")):
            self.assertEqual(self.service().build_report()["status"], "SYNTHETIC_EVALUATED")


if __name__ == "__main__":
    unittest.main()
