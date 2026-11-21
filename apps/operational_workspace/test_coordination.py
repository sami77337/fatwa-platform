"""Independent current grants, policy pins and native human administrative forms."""

from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.case_assignments import services as assignments
from apps.case_assignments.models import AssignmentEvent, PriorityEvent
from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import post

from . import coordination, views
from .boundary import digest
from .coordination_test_support import COORDINATION_FEATURES, CoordinationFixture
from .test_support import CREDENTIALS


@override_settings(**COORDINATION_FEATURES)
class OperationalCoordinationTests(CoordinationFixture, TransactionTestCase):
    def test_multiple_priority_updates_keep_native_numeric_history_order(self):
        for index in range(12):
            self.prioritize(
                value="fixture_urgent" if index % 2 == 0 else "fixture_normal",
                expected_version=index,
                reason=f"تعديل بشري متتابع رقم {index + 1}",
            )
        row = self.view()
        self.assertEqual(row["priority"]["version"], 12)
        self.assertEqual(
            [x["sequence"] for x in row["priority"]["history"]], list(range(12, 0, -1))
        )
        self.assertEqual(self.immutable_sources(), self.originals)

    def test_actual_roles_write_explicit_assignment_and_human_priority_without_core_changes(self):
        self.prioritize()
        result = self.assign()
        self.assertEqual(result["assignment"]["primary_subject"], "mufti")
        self.assertEqual(result["priority"]["value"], "fixture_urgent")
        self.assertEqual(AssignmentEvent.objects.get().actor_role, "ORGANIZER")
        self.assertEqual(PriorityEvent.objects.get().subject_id, "operator")
        self.assertEqual(
            assignments.read_assignment(
                case_id=self.target["case_id"],
                subject_id="mufti",
                provider=self.directory,
                synthetic_fixtures_only=True,
            )["primary_subject"],
            "mufti",
        )
        self.assertEqual(self.immutable_sources(), self.originals)
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                case_id=self.target["case_id"],
                **self.common,
                text="غير مسموح",
                expected_revision=3,
                expected_evidence_version=1,
            )

    def test_read_does_not_grant_write_and_one_target_does_not_grant_another(self):
        self.authority.revoke(action="SET_PRIORITY")
        self.assertEqual(self.view()["priority_options"], [])
        with self.assertRaises(cases.CaseConflict):
            self.prioritize()
        allowed = set(self.authority.resources)
        target = coordination.resource(
            Case.objects.get(pk=self.target["case_id"]),
            target="mufti",
            target_epoch="epoch-1",
        )
        self.authority.resources = {
            row for row in allowed if not (row[3] == "SET_PRIMARY" and row[4] == digest(target))
        }
        with self.assertRaises(cases.CaseConflict):
            self.assign()
        self.assign(target_subject="mufti2")
        self.assertFalse(PriorityEvent.objects.exists())

    def test_disabled_missing_or_unversioned_policy_and_identity_fail_closed(self):
        for setting, value in (
            ("FATWA_OPERATIONAL_COORDINATION_ENABLED", False),
            ("FATWA_CASE_ASSIGNMENTS_ENABLED", False),
            ("FATWA_OPERATIONAL_PRIORITY_POLICY", None),
            ("FATWA_CASE_ASSIGNMENT_CANDIDATES", lambda actor, ref: ["mufti"]),
            ("FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with (
                self.subTest(setting=setting),
                override_settings(**{setting: value}),
                self.assertRaises(cases.CaseConflict),
            ):
                self.view()

    def test_candidate_cannot_expand_scope_role_or_expired_identity(self):
        original = self.directory.identities["mufti"]
        for changed in (
            replace(original, role="ORGANIZER"),
            replace(original, active=False),
            replace(original, case_keys=frozenset({"other"})),
        ):
            self.directory.identities["mufti"] = changed
            with self.assertRaises(cases.CaseConflict):
                self.assign()
        self.directory.identities["mufti"] = original
        with self.assertRaises(cases.CaseConflict):
            self.assign(target_epoch="old-epoch")
        self.assertFalse(AssignmentEvent.objects.exists())

    def test_final_callbacks_and_render_revocation_roll_back_every_write(self):
        authority_grants = set(self.authority.resources)
        with self.assertRaises(cases.CaseConflict):
            with coordination.set_priority(
                **self.common, **self.values(value="fixture_urgent", policy_sha256=self.policy_sha)
            ):
                self.authority.revoke(action="SET_PRIORITY")
        self.assertFalse(PriorityEvent.objects.exists())
        self.authority.resources = authority_grants
        with self.assertRaises(cases.CaseConflict):
            with coordination.assign(
                **self.common,
                **self.values(action="SET_PRIMARY", target_subject="mufti", target_epoch="epoch-1"),
            ):
                self.directory.identities["mufti"] = replace(
                    self.directory.identities["mufti"], active=False
                )
        self.assertFalse(AssignmentEvent.objects.exists())

    def test_last_callback_cannot_change_earlier_target_or_priority_policy(self):
        self.authority.hook = lambda values: (
            setattr(
                self.priorities,
                "options",
                (coordination.PriorityOption("replacement", "تغيرت", 0),),
            )
            if values["action"] == "SET_PRIORITY"
            else None
        )
        with self.assertRaises(cases.CaseConflict):
            self.prioritize()
        self.assertFalse(PriorityEvent.objects.exists())

    def test_changed_options_fingerprint_unknown_values_and_unconfirmed_form_are_denied(self):
        for changes in (
            {"value": "injected"},
            {"policy_sha256": "0" * 64},
            {"confirmed": False},
            {"expected_revision": 1},
            {"reason": " "},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.prioritize(**changes)
        self.assertFalse(PriorityEvent.objects.exists())

    def test_native_csrf_strict_fields_actual_role_and_late_render_denial(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        base = "/casework/operations/"
        login = client.get(base + "login/")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(
            post(
                client,
                base + "login/",
                {"credential": CREDENTIALS["operator"]},
                login,
            ).status_code,
            303,
        )
        page = post(
            client,
            base,
            {
                "action": "coordination",
                "case_ref": self.target["public_ref"],
            },
            login,
        )
        self.assertContains(page, 'id="ops-priority-form"')
        self.assertContains(page, "ORGANIZER")
        values = self.values()
        payload = {
            "action": "coordination_priority",
            "case_ref": values["case_ref"],
            "reason": values["reason"],
            "confirmed": "yes",
            "command_id": values["command_id"],
            "version": 0,
            "revision": values["expected_revision"],
            "evidence_version": values["expected_evidence_version"],
            "priority": "fixture_urgent",
            "policy_sha256": self.policy_sha,
        }
        self.assertEqual(
            client.post(
                base, urlencode(payload), content_type="application/x-www-form-urlencoded"
            ).status_code,
            403,
        )
        self.assertEqual(post(client, base, {**payload, "role": "MUFTI"}, page).status_code, 409)
        original = views.render
        from . import coordination_views

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.authority.revoke(action="SET_PRIORITY")
            return result

        with patch.object(coordination_views, "render", side_effect=revoke):
            self.assertEqual(post(client, base, payload, page).status_code, 409)
        self.assertFalse(PriorityEvent.objects.exists())
        self.assertEqual(self.immutable_sources(), self.originals)
