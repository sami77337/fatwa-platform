"""Independent regressions for collection authorization at the final boundary."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import CaseEvent

from . import services
from .tests import AssignmentFixture


@override_settings(FATWA_CASE_ASSIGNMENTS_ENABLED=True, FATWA_CASE_ASSIGNMENT_CANDIDATES=None)
class AssignmentFinalAuthorizationTests(AssignmentFixture, TransactionTestCase):
    def test_scope_removal_during_last_row_cannot_return_previously_allowed_case(self):
        second = self.intake("review-second")
        self.grant_all(second)
        common = {key: value for key, value in self.common().items() if key != "case_id"}
        rows = cases.list_cases(**common)
        final_ref = sorted(rows, key=lambda row: row["case_id"])[-1]["public_ref"]
        original = services._projection
        seen = 0

        def removed(*args, **kwargs):
            nonlocal seen
            result = original(*args, **kwargs)
            seen += 1
            if seen == 2:
                self.directory.identities["mufti-a"] = replace(
                    self.directory.identities["mufti-a"],
                    case_keys=frozenset({final_ref}),
                )
            return result

        with patch.object(services, "_projection", side_effect=removed):
            with self.assertRaises(cases.CaseConflict):
                services.annotate_queue(rows, **common)

    def test_scope_reduction_between_rows_is_caught_by_final_batch_boundary(self):
        second = self.intake("review-between-rows")
        self.grant_all(second)
        common = {key: value for key, value in self.common().items() if key != "case_id"}
        rows = cases.list_cases(**common)
        final_ref = sorted(rows, key=lambda row: row["case_id"])[-1]["public_ref"]
        original = services.read_assignment
        seen = 0

        def remove_before_next_row(**kwargs):
            nonlocal seen
            seen += 1
            if seen == 2:
                self.directory.identities["mufti-a"] = replace(
                    self.directory.identities["mufti-a"],
                    case_keys=frozenset({final_ref}),
                )
            # This row starts after revocation, remains in scope, and passes all
            # of its own identity checks. The batch must still omit the earlier
            # now-revoked row by refusing the entire projection.
            return original(**kwargs)

        with patch.object(services, "read_assignment", side_effect=remove_before_next_row):
            with self.assertRaisesMessage(cases.CaseConflict, "assignment_identity_changed"):
                services.annotate_queue(rows, **common)
        self.assertEqual(seen, 2)

    def test_batch_accepts_refreshed_expiry_and_does_not_create_events(self):
        second = self.intake("review-refresh")
        self.grant_all(second)
        common = {key: value for key, value in self.common().items() if key != "case_id"}
        original = self.directory.resolve

        def refreshed(subject_id):
            identity = original(subject_id)
            return replace(identity, valid_until=timezone.now() + timedelta(minutes=30))

        before = list(CaseEvent.objects.values())
        with patch.object(self.directory, "resolve", side_effect=refreshed):
            rows = cases.list_cases(**common)
            result = services.annotate_queue(rows, **common)
        self.assertEqual(len(result), 2)
        self.assertEqual(before, list(CaseEvent.objects.values()))
