"""Real organizer proposals/reviews preserve sources and reject stale current authority."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.scholarly_links import services as scholarly
from apps.scholarly_links.models import CaseLessonLink, LinkDecision
from tests.casework.test_http import hidden, post

from . import lesson_links, views
from .lesson_test_support import LESSON_FEATURES, LessonDomainAuthority, LessonFixture
from .test_support import CREDENTIALS

BASE = "/casework/operations/"


@override_settings(**LESSON_FEATURES)
class OperationalLessonTests(LessonFixture, TransactionTestCase):
    def test_real_organizer_link_review_and_withdrawal_reuse_mufti_journal_without_source_change(
        self,
    ):
        proposed = self.propose_lesson()
        self.assertEqual(proposed["role"], "ORGANIZER")
        self.assertEqual(proposed["links"][0]["state"], "PROPOSED")
        approved = self.review_lesson()
        self.assertEqual(approved["role"], "ORGANIZER_ADMIN")
        self.assertEqual(approved["links"][0]["state"], "APPROVE")
        mufti = scholarly.desk(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(mufti["lesson_links"][0]["created_by"], "operator")
        self.assertEqual(mufti["lesson_links"][0]["history"][0]["actor"], "admin")
        self.assertEqual(self.review_lesson(action="WITHDRAW")["links"][0]["state"], "WITHDRAW")
        self.assertEqual(self.immutable_lesson_sources(), self.lesson_originals)
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common,
                case_id=self.target["case_id"],
                text="محاولة غير مخولة",
                expected_revision=3,
                expected_evidence_version=1,
            )

    def test_read_propose_and_review_are_independent_of_actual_role(self):
        self.authority.revoke(action="PROPOSE_LESSON_LINK")
        with self.assertRaises(cases.CaseConflict):
            self.propose_lesson()
        with lesson_links.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(len(result["catalog"]), 2)
            self.assertFalse(any(row["can_propose"] for row in result["catalog"]))
        with lesson_links.propose(**{**self.common, "subject_id": "mufti"}, **self.lesson_values()):
            pass
        self.authority.revoke(subject="admin", action="APPROVE_LESSON_LINK")
        with self.assertRaises(cases.CaseConflict):
            self.review_lesson()
        self.assertEqual(LinkDecision.objects.count(), 0)
        self.assertEqual(self.immutable_lesson_sources(), self.lesson_originals)

    def test_scoped_lesson_and_exact_link_reads_hide_cards_labels_and_counts(self):
        self.propose_lesson()
        self.authority.revoke(action="READ_OPERATIONAL_LESSON")
        with lesson_links.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["catalog"], [])
            self.assertEqual(result["links"], [])
        with self.assertRaises(cases.CaseConflict):
            self.propose_lesson()
        self.assertEqual(self.immutable_lesson_sources(), self.lesson_originals)

    def test_target_scope_and_domain_denial_cannot_be_replaced_by_operational_grant(self):
        self.lesson_authority.rules = {
            row
            for row in self.lesson_authority.rules
            if not (row[0] == "operator" and row[3] == "READ_LESSON")
        }
        with lesson_links.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["catalog"], [])
        with self.assertRaises(cases.CaseConflict):
            self.propose_lesson()
        actor = self.directory.identities["admin"]
        self.directory.identities["admin"] = replace(
            actor, case_keys=actor.case_keys - {self.receipts["lessons"]["public_ref"]}
        )
        with lesson_links.projection(
            **{**self.common, "subject_id": "admin"}, case_ref=self.target["public_ref"]
        ) as result:
            self.assertEqual(result["catalog"], [])
        self.assertEqual(self.state(), self.originals)

    def test_flags_missing_authority_and_hidden_cases_are_closed(self):
        for name, value in (
            ("FATWA_OPERATIONAL_LESSON_LINKS_ENABLED", False),
            ("FATWA_SCHOLARLY_LINKS_ENABLED", False),
            ("FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("FATWA_SCHOLARLY_LINKS_AUTHORITY", None),
        ):
            with override_settings(**{name: value}), self.assertRaises(cases.CaseConflict):
                self.propose_lesson()
        for key in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                self.propose_lesson(case_ref=self.receipts[key]["public_ref"])
        self.assertEqual(self.state(), self.originals)

    def test_invalid_source_pins_spans_and_descriptive_lesson_timing_never_write(self):
        for changes in (
            {"lesson_sha256": "0" * 64},
            {"expected_revision": 1},
            {"expected_target_evidence_version": 2},
            {"start_ms": 100, "end_ms": 10},
            {"start_ms": None, "end_ms": 100},
            {"start_ms": 999999, "end_ms": None},
            {
                "lesson_version_id": str(self.descriptive.pk),
                "lesson_sha256": self.descriptive.sha256,
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.propose_lesson(**changes)
        self.assertEqual(self.state(), self.originals)
        result = self.propose_lesson(
            lesson_version_id=str(self.descriptive.pk),
            lesson_sha256=self.descriptive.sha256,
            start_ms=None,
            end_ms=None,
        )
        self.assertFalse(result["links"][0]["lesson"]["source_available"])
        self.assertFalse(any(row["can_read_media"] for row in result["catalog"]))

    def test_exact_retries_do_not_duplicate_and_review_cas_and_changed_input_conflict(self):
        values = self.lesson_values()
        for _ in range(2):
            with lesson_links.propose(**self.common, **values):
                pass
        self.assertEqual(CaseLessonLink.objects.filter(case_id=self.target["case_id"]).count(), 1)
        with self.assertRaises(cases.CaseConflict):
            with lesson_links.propose(
                **self.common, **{**values, "reason": "محتوى مختلف بنفس المفتاح"}
            ):
                pass
        with self.assertRaises(cases.CaseConflict):
            self.propose_lesson()
        with self.assertRaises(cases.CaseConflict):
            self.review_lesson(expected_sequence=1)
        review = self.review_values()
        for _ in range(2):
            with lesson_links.decide(**{**self.common, "subject_id": "admin"}, **review):
                pass
        self.assertEqual(LinkDecision.objects.count(), 1)
        self.authority.revoke(subject="admin", action="APPROVE_LESSON_LINK")
        with self.assertRaises(cases.CaseConflict):
            with lesson_links.decide(**{**self.common, "subject_id": "admin"}, **review):
                pass
        self.assertEqual(self.immutable_lesson_sources(), self.lesson_originals)

    def test_late_domain_revocation_and_equal_epoch_replacement_roll_back_decisions(self):
        self.propose_lesson()
        before = self.state()
        rules = set(self.lesson_authority.rules)
        with self.assertRaises(cases.CaseConflict):
            with lesson_links.decide(
                **{**self.common, "subject_id": "admin"}, **self.review_values()
            ):
                self.lesson_authority.rules = {
                    row for row in rules if not (row[0] == "admin" and row[3] == "APPROVE")
                }
        self.lesson_authority.rules = rules
        self.assertEqual(self.state(), before)
        original = settings.FATWA_SCHOLARLY_LINKS_AUTHORITY
        try:
            with self.assertRaises(cases.CaseConflict):
                with lesson_links.decide(
                    **{**self.common, "subject_id": "admin"}, **self.review_values()
                ):
                    replacement = LessonDomainAuthority()
                    replacement.rules = set(rules)
                    settings.FATWA_SCHOLARLY_LINKS_AUTHORITY = replacement
        finally:
            settings.FATWA_SCHOLARLY_LINKS_AUTHORITY = original
        self.assertEqual(self.state(), before)

    def test_unrelated_metadata_append_cannot_be_adopted_as_a_lesson_write(self):
        original = scholarly._append_lesson_link_locked

        def append_then_change(**kwargs):
            result = original(**kwargs)
            organization.save(
                case_id=self.target["case_id"],
                subject_id="mufti",
                provider=self.directory,
                tags=["تغيير جانبي"],
                question_types=["TIME"],
                note="",
                command_id=uuid.uuid4(),
                expected_metadata_version=1,
                expected_revision=3,
                expected_evidence_version=1,
                synthetic_fixtures_only=True,
            )
            return result

        with (
            patch.object(scholarly, "_append_lesson_link_locked", append_then_change),
            self.assertRaises(cases.CaseConflict),
        ):
            self.propose_lesson()
        self.assertEqual(self.state(), self.originals)

    def login(self, subject="operator"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get(BASE + "login/")
        self.assertEqual(
            post(client, BASE + "login/", {"credential": CREDENTIALS[subject]}, page).status_code,
            303,
        )
        page = client.get(BASE)
        self.assertContains(page, 'id="ops-lessons-index"')
        page = post(
            client, BASE, {"action": "lesson_links", "case_ref": self.target["public_ref"]}, page
        )
        self.assertEqual(page.status_code, 200, page.content)
        return client, page

    def test_native_proposal_and_admin_review_forms_persist_exact_version_and_real_actor(self):
        client, page = self.login()
        # Catalog sorting is stable by lesson identity, so use the server-pinned card's values.
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "target_revision",
                "target_evidence_version",
                "lesson_version_id",
                "lesson_sha256",
                "command_id",
            )
        }
        page = post(
            client,
            BASE,
            {
                **fields,
                "action": "lesson_link_propose",
                "reason": "رابط من الواجهة <script>نص</script>",
                "start_ms": "",
                "end_ms": "",
            },
            page,
        )
        self.assertContains(page, 'id="ops-lesson-saved"')
        self.assertContains(page, "&lt;script&gt;نص&lt;/script&gt;")
        self.assertNotContains(page, "ملاحظة داخلية لا تعرضها قائمة التشغيل")
        reviewer, page = self.login("admin")
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "target_revision",
                "target_evidence_version",
                "link_id",
                "link_sha256",
                "sequence",
                "command_id",
            )
        }
        page = post(
            reviewer,
            BASE,
            {
                **fields,
                "action": "lesson_link_decide",
                "decision": "APPROVE",
                "note": "مراجعة مستقلة للربط",
                "confirmed": "yes",
            },
            page,
        )
        self.assertContains(page, "ربط اعتمده إنسان")
        self.assertContains(page, "ORGANIZER_ADMIN")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(LinkDecision.objects.get().subject_id, "admin")
        self.assertEqual(self.immutable_lesson_sources(), self.lesson_originals)

    def test_native_forgery_csrf_and_last_render_revocation_discard_pending_link(self):
        client, page = self.login()
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "target_revision",
                "target_evidence_version",
                "lesson_version_id",
                "lesson_sha256",
                "command_id",
            )
        }
        fields.update(action="lesson_link_propose", reason="لا يحفظ دون تفويض")
        self.assertEqual(client.post(BASE, fields).status_code, 403)
        for extra in ({"role": "MUFTI"}, {"kind": "REFERRED_BY_SHEIKH"}, {"answer": "تجاوز"}):
            self.assertEqual(post(client, BASE, {**fields, **extra}, page).status_code, 409)
        render = views.render

        def revoked_after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.revoke(action="PROPOSE_LESSON_LINK")
            return response

        with patch.object(views, "render", revoked_after_render):
            self.assertEqual(post(client, BASE, fields, page).status_code, 409)
        self.assertEqual(self.state(), self.originals)
