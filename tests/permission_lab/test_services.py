"""Adversarial hypothetical permission checks; no database is permitted."""

from dataclasses import FrozenInstanceError
from itertools import product
from unittest.mock import patch

from django.test import SimpleTestCase


class PermissionServiceTests(SimpleTestCase):
    def service(self):
        from apps.permission_lab import services

        return services

    def reasons(self, decision):
        self.assertEqual(decision.effect, "DENY")
        self.assertIs(decision.allowed, False)
        self.assertTrue(all(reason.message for reason in decision.reasons))
        return {reason.code for reason in decision.reasons}

    def test_mapped_mufti_candidate_stays_denied_pending_approval(self):
        # A mapped MUFTI candidate must remain denied while approval is pending.
        decision = self.service().evaluate("MUFTI", "synthetic::answer.create", "synthetic::answer")
        self.assertTrue(decision.valid_combination)
        self.assertEqual(decision.candidate_roles, ("MUFTI",))
        self.assertTrue(
            {"DENY_DEFAULT", "POLICY_PENDING", "CANDIDATE_ONLY"} <= self.reasons(decision)
        )

    def test_admin_peer_does_not_inherit_scholarly_authority(self):
        decision = self.service().evaluate(
            "ORGANIZER_ADMIN", "synthetic::answer.create", "synthetic::answer"
        )
        self.assertIn("SCHOLARLY_AUTHORITY_RESTRICTED", self.reasons(decision))
        self.assertIn("ACTOR_NOT_CANDIDATE", self.reasons(decision))

    def test_fixed_internal_effects_never_become_runnable(self):
        for actor in ("MUFTI", "ORGANIZER_ADMIN", "ORGANIZER", "DOMAIN_TRANSACTION"):
            for action, resource in (
                ("P00-03::case.project", "synthetic::case"),
                ("P00-03::delivery.hold", "synthetic::delivery"),
            ):
                decision = self.service().evaluate(actor, action, resource)
                self.assertIn("INTERNAL_EFFECT_ONLY", self.reasons(decision))
                self.assertEqual(decision.candidate_roles, ())
                if actor == "DOMAIN_TRANSACTION":
                    self.assertFalse(decision.valid_combination)
                    self.assertIn("INTERNAL_PRINCIPAL_FORBIDDEN", self.reasons(decision))

    def test_cross_resource_matching_is_rejected_without_target_fallback(self):
        for action, resource in (
            ("synthetic::answer.create", "synthetic::catalog"),
            ("synthetic::catalog.inspect", "synthetic::answer"),
            ("start_review", "synthetic::answer"),
            ("synthetic::answer.draft", "workflow::UNREVIEWED"),
        ):
            decision = self.service().evaluate("MUFTI", action, resource)
            self.assertFalse(decision.valid_combination)
            self.assertIn("ACTION_RESOURCE_MISMATCH", self.reasons(decision))
            self.assertIsNone(decision.workflow_target)

    def test_synthetic_transition_remains_disabled(self):
        decision = self.service().evaluate("MUFTI", "synthetic::answer.draft", "synthetic::answer")
        self.assertTrue(decision.valid_combination)
        self.assertEqual(decision.workflow_target, "SYNTHETIC_REVIEW")
        self.assertIn("TRANSITION_DISABLED", self.reasons(decision))

    def test_workflow_checks_exact_current_state_but_never_executes(self):
        expected = {
            ("UNREVIEWED", "start_review"): "IN_REVIEW",
            ("NEEDS_CHANGES", "start_review"): "IN_REVIEW",
            ("IN_REVIEW", "request_changes"): "NEEDS_CHANGES",
            ("IN_REVIEW", "complete_review"): "REVIEWED_INTERNAL",
        }
        for state, action in product(
            ("UNREVIEWED", "IN_REVIEW", "NEEDS_CHANGES", "REVIEWED_INTERNAL"),
            ("start_review", "request_changes", "complete_review"),
        ):
            decision = self.service().evaluate("MUFTI", action, "workflow::" + state)
            self.assertEqual(decision.workflow_target, expected.get((state, action)))
            self.assertEqual(decision.valid_combination, (state, action) in expected)
            self.assertIn(
                "WORKFLOW_NOT_AUTHORIZATION"
                if (state, action) in expected
                else "WORKFLOW_TRANSITION_INVALID",
                self.reasons(decision),
            )

    def test_every_catalog_combination_is_denied(self):
        service = self.service()
        catalog = service.build_catalog()
        for actor, action, resource in product(catalog.actors, catalog.actions, catalog.resources):
            with self.subTest(actor=actor, action=action, resource=resource.id):
                self.reasons(service.evaluate(actor, action, resource.id))

    def test_unknown_tokens_and_real_case_ids_never_resolve(self):
        for field, value, code in (
            (0, "SUPERUSER", "UNKNOWN_ACTOR"),
            (1, "approve", "UNKNOWN_ACTION"),
            (2, "case-123", "UNKNOWN_RESOURCE"),
        ):
            values = ["MUFTI", "synthetic::answer.create", "synthetic::answer"]
            values[field] = value
            decision = self.service().evaluate(*values)
            self.assertFalse(decision.valid_combination)
            self.assertIn(code, self.reasons(decision))

    def test_malformed_values_are_not_normalized_or_coerced(self):
        for value in (
            None,
            True,
            1,
            [],
            {},
            "",
            "*",
            " MUFTI",
            "MUFTI ",
            "mufti",
            "MUFTI\x00",
            "MUFTI\u200b",
            "ＭＵＦＴＩ",
            "../MUFTI",
            "x" * 97,
        ):
            for index in range(3):
                values = ["MUFTI", "synthetic::answer.create", "synthetic::answer"]
                values[index] = value
                with self.subTest(index=index, value=value):
                    decision = self.service().evaluate(*values)
                    self.assertFalse(decision.valid_combination)
                    self.reasons(decision)

    def test_results_are_immutable_and_do_not_grant_on_candidate_mutation(self):
        service = self.service()
        decision = service.evaluate("MUFTI", "synthetic::answer.create", "synthetic::answer")
        with self.assertRaises(FrozenInstanceError):
            decision.allowed = True
        from apps.permission_lab.sources import load_inventory

        source = load_inventory()
        source["actions"][2]["candidate_principals"].append({"kind": "ROLE", "name": "ORGANIZER"})
        after = service.evaluate("ORGANIZER", "synthetic::answer.create", "synthetic::answer")
        self.assertEqual(after.candidate_roles, ("MUFTI",))
        self.assertIn("ACTOR_NOT_CANDIDATE", self.reasons(after))

    def test_missing_sources_raise_closed_failure_without_partial_catalog(self):
        service = self.service()
        from apps.permission_lab.sources import SourceUnavailable

        with patch.object(service, "load_inventory", side_effect=SourceUnavailable("unavailable")):
            with self.assertRaises(SourceUnavailable):
                service.build_catalog()
            with self.assertRaises(SourceUnavailable):
                service.evaluate("MUFTI", "synthetic::answer.create", "synthetic::answer")

    def test_historical_missing_is_visible_even_for_valid_combination(self):
        decision = self.service().evaluate("MUFTI", "synthetic::answer.create", "synthetic::answer")
        self.assertIn("HISTORICAL_INVENTORY_UNAVAILABLE", self.reasons(decision))
