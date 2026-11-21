"""Real-role operational reads, independent grants and unchanged canonical history."""

import copy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.casework.models import Case

from . import identity, services
from .boundary import digest, source_rows
from .test_support import FEATURES, OperationalFixture


@override_settings(**FEATURES)
class OperationalWorkspaceTests(OperationalFixture, TransactionTestCase):
    def queue(self, **changes):
        with services.queue_projection(**{**self.common, **changes}) as result:
            return result

    def detail(self, kind, section):
        with services.detail_projection(
            **self.common, case_ref=self.receipts[kind]["public_ref"], section=section
        ) as result:
            return result

    def save_metadata(self):
        row = Case.objects.get(pk=self.receipts["metadata"]["case_id"])
        return organization.save(
            case_id=str(row.pk),
            subject_id="mufti",
            provider=self.directory,
            tags=["وسم اختاره إنسان"],
            question_types=["EDUCATION"],
            note="ملاحظة تشغيلية اصطناعية خاصة",
            command_id="00000000-0000-4000-8000-000000000001",
            expected_metadata_version=0,
            expected_revision=row.revision,
            expected_evidence_version=row.evidence_version,
            synthetic_fixtures_only=True,
        )

    def test_real_pending_states_and_exact_counts_exclude_hidden_and_unscoped_cases(self):
        result = self.queue()
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertEqual(
            result["counts"],
            {
                "all": 5,
                "metadata": 5,
                "delivery": 1,
                "publication": 1,
                "transcript": 1,
                "capability": 3,
            },
        )
        expected = {
            row["public_ref"]
            for key, row in self.receipts.items()
            if key not in {"hidden", "unscoped"}
        }
        self.assertEqual({row["public_ref"] for row in result["rows"]}, expected)
        for key in ("hidden", "unscoped"):
            self.assertNotIn(self.receipts[key]["public_ref"], repr(result))
            self.assertNotIn(self.receipts[key]["case_id"], repr(result))
        for selected in services.SECTION_ACTIONS:
            filtered = self.queue(selected_filter=selected)
            self.assertEqual(filtered["counts"], result["counts"])
            self.assertEqual(len(filtered["rows"]), result["counts"][selected])
        self.assertEqual(self.state(), self.originals)

    def test_each_detail_is_actual_status_without_transcript_publication_or_recipient_content(self):
        self.assertEqual(self.detail("delivery", "delivery")["section"]["failed_parts"], 1)
        self.assertTrue(self.detail("publication", "publication")["section"]["pending"])
        recorded = self.detail("transcript", "transcript")["section"]
        self.assertEqual(recorded["versions"][0]["change_kind"], "MEANING_REVIEW")
        self.assertNotIn("text", recorded)
        self.assertNotIn("raw", recorded)
        capability = self.detail("capability", "capability")["section"]
        self.assertEqual(capability["channel"], "WEBSITE")
        self.assertTrue(capability["pending"])
        self.assertNotIn("sender", repr(capability))
        self.assertEqual(self.state(), self.originals)

    def test_action_revocation_omits_facet_without_losing_other_authorized_case_sections(self):
        self.authority.revoke(action="READ_DELIVERY")
        result = self.queue()
        self.assertEqual(result["counts"]["delivery"], 0)
        self.assertEqual(result["counts"]["metadata"], 5)
        self.assertNotIn("FAILED_REQUIRES_REVIEW", repr(result))
        with self.assertRaises(cases.CaseConflict):
            self.detail("delivery", "delivery")
        for kind in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                self.detail(kind, "metadata")
        self.assertEqual(self.state(), self.originals)

    def test_actual_roles_are_preserved_and_organizers_cannot_save_or_approve_scholarly_answers(
        self,
    ):
        for subject, role in (
            ("operator", "ORGANIZER"),
            ("admin", "ORGANIZER_ADMIN"),
            ("mufti", "MUFTI"),
        ):
            self.assertEqual(self.queue(subject_id=subject)["role"], role)
        receipt = self.receipts["metadata"]
        for subject in ("operator", "admin"):
            common = dict(
                case_id=receipt["case_id"],
                subject_id=subject,
                provider=self.directory,
                synthetic_fixtures_only=True,
            )
            with self.assertRaisesMessage(cases.CaseConflict, "case_access_denied"):
                cases.save_answer(
                    **common, expected_revision=1, expected_evidence_version=1, text="غير مخول"
                )
            with self.assertRaisesMessage(cases.CaseConflict, "case_access_denied"):
                cases.record_decision(
                    **common,
                    answer_id="00000000-0000-4000-8000-000000000000",
                    expected_revision=1,
                    expected_evidence_version=1,
                    action="APPROVE",
                )
        self.assertEqual(self.state(), self.originals)

    def test_same_named_impostor_directory_and_wrapped_old_configuration_fail_closed(self):
        impostor = copy.copy(self.directory)
        with self.assertRaises(cases.CaseConflict):
            self.queue(provider=impostor)
        wrapper = identity.RequestDirectory(self.directory, self.directory.identities["operator"])
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=impostor):
            with self.assertRaises(cases.CaseConflict):
                self.queue(provider=wrapper)
        with services.queue_projection(**{**self.common, "provider": wrapper}) as result:
            self.assertEqual(result["counts"]["all"], 5)

    def test_disabled_missing_current_trust_invalid_role_and_nonliteral_grant_never_authorize(self):
        for name, value in (
            ("FATWA_OPERATIONAL_WORKSPACE_ENABLED", False),
            ("FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{name: value}), self.assertRaises(cases.CaseConflict):
                self.queue()
        old = self.directory.identities["operator"]
        self.directory.identities["operator"] = replace(old, role="REQUESTER")
        with self.assertRaises(cases.CaseConflict):
            self.queue()
        self.directory.identities["operator"] = old
        with patch.object(self.authority, "permits", return_value="ALLOW"):
            self.assertEqual(self.queue()["rows"], [])
        with patch.object(self.directory, "projection_epoch", return_value=""):
            with self.assertRaises(cases.CaseConflict):
                self.queue()

    def test_expired_actor_session_or_grant_deadline_is_rejected(self):
        old = self.directory.identities["operator"]
        self.directory.identities["operator"] = replace(
            old, valid_until=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(cases.CaseConflict):
            self.queue()
        self.directory.identities["operator"] = old
        with self.assertRaises(cases.CaseConflict):
            self.queue(session_deadline=timezone.now() - timedelta(seconds=1))
        with patch.object(
            self.authority, "grant_deadline", return_value=timezone.now() - timedelta(seconds=1)
        ):
            with self.assertRaises(cases.CaseConflict):
                self.queue()

    def test_revocation_and_identity_role_change_after_projection_invalidate_the_complete_result(
        self,
    ):
        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(**self.common):
                self.authority.revoke(
                    action="READ_CASE", case_ref=self.receipts["metadata"]["public_ref"]
                )
        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(**self.common):
                self.directory.identities["operator"] = replace(
                    self.directory.identities["operator"], role="MUFTI"
                )
        self.assertEqual(self.state(), self.originals)

    def test_last_policy_callback_cannot_revoke_an_earlier_checked_case_and_leak_it(self):
        target = self.receipts["metadata"]["public_ref"]
        fired = []

        def late(values):
            if values["action"] == "READ_CAPABILITY" and not fired:
                fired.append(True)
                self.authority.revoke(action="READ_CASE", case_ref=target)

        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(**self.common):
                self.authority.hook = late
        self.assertTrue(fired)

    def test_actual_metadata_append_during_final_render_is_detected_and_rolled_back(self):
        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(**self.common):
                self.save_metadata()
        self.assertEqual(self.state(), self.originals)

    def test_real_metadata_completion_changes_queue_without_changing_original_case_answer_or_decision(
        self,
    ):
        case_ids = [row["case_id"] for row in self.receipts.values()]
        before = source_rows(case_ids)
        self.save_metadata()
        self.assertEqual(self.queue()["counts"]["metadata"], 4)
        self.assertEqual(self.queue()["counts"]["all"], 4)
        after = source_rows(case_ids)
        for table in (
            "casework_case",
            "casework_casesource",
            "casework_answerrevision",
            "casework_casedecision",
        ):
            self.assertEqual(digest(before[table]), digest(after[table]))

    def test_versioned_current_capability_changes_are_live_and_unversioned_readers_are_issues(self):
        self.profiles.value = replace(
            self.profiles.value,
            capabilities=replace(
                self.profiles.value.capabilities,
                supported=frozenset({"text", "document", "audio", "image"}),
            ),
        )
        self.assertEqual(self.queue()["counts"]["capability"], 0)
        with override_settings(FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profiles.value):
            self.assertEqual(self.queue()["counts"]["capability"], 4)
        self.assertEqual(self.state(), self.originals)

    def test_late_profile_or_same_value_policy_replacement_is_not_a_current_snapshot(self):
        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(**self.common):
                self.profiles.value = replace(self.profiles.value, max_media_bytes=2)
        old = settings.FATWA_OPERATIONAL_WORKSPACE_AUTHORITY
        try:
            with self.assertRaises(cases.CaseConflict):
                with services.queue_projection(**self.common):
                    settings.FATWA_OPERATIONAL_WORKSPACE_AUTHORITY = copy.copy(old)
        finally:
            settings.FATWA_OPERATIONAL_WORKSPACE_AUTHORITY = old

    def test_unknown_filter_or_action_never_expands_the_allowed_projection(self):
        for value in ("*", "ALL", None, []):
            with self.assertRaises(cases.CaseConflict):
                self.queue(selected_filter=value)
        with self.assertRaises(cases.CaseConflict):
            self.detail("metadata", "APPROVE")
