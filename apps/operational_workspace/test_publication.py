"""Explicit organizer publication transitions never supply scholarly or text-edit authority."""

from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.experimental_publication import services as editorial
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.public_answer_media import services as recording
from tests.casework.test_http import hidden, post

from . import publication, views
from .publication_test_support import (
    PUBLICATION_FEATURES,
    PublicationDomainAuthority,
    PublicationFixture,
    grant_publication,
)
from .test_support import CREDENTIALS

BASE = "/casework/operations/"


@override_settings(**PUBLICATION_FEATURES)
class OperationalPublicationTests(PublicationFixture, TransactionTestCase):
    def test_existing_recording_reader_resolves_publication_actors_without_widening_canonical_authors(
        self,
    ):
        self.publication_decide()
        self.publication_decide(subject="admin", action="APPROVE")
        with override_settings(FATWA_PUBLIC_ANSWER_MEDIA_ENABLED=True):
            with recording.staff_boundary(
                case_id=self.target["case_id"],
                subject_id="mufti",
                provider=self.directory,
                synthetic_fixtures_only=True,
            ) as (guard, actor):
                self.assertEqual(recording._publication(guard, self.edition.pk).pk, self.edition.pk)
                part, _pins, raw = recording._source(guard, actor, self.part.pk)
                self.assertEqual(part.pk, self.part.pk)
                self.assertTrue(raw)

    def test_actual_organizer_review_admin_approval_and_withdrawal_preserve_mufti_source(self):
        reviewed = self.publication_decide()
        self.assertEqual(reviewed["role"], "ORGANIZER")
        result = self.publication_decide(subject="admin", action="APPROVE")
        self.assertEqual(result["role"], "ORGANIZER_ADMIN")
        self.assertEqual(result["editions"][0]["state"], "PUBLISHED")
        with (
            override_settings(FATWA_LIBRARY_PREVIEW_POLICY=None),
            self.assertRaises(preview.PreviewUnavailable),
        ):
            preview.read(str(self.edition.pk))
        policy = PreviewPolicy(
            (PublicationGrant(str(self.edition.pk), self.edition.content_sha256),),
            (),
            self.authority.until,
            True,
        )
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=policy,
            FATWA_CASE_CITATIONS_ENABLED=True,
            FATWA_KNOWLEDGE_LINKS_ENABLED=True,
        ):
            self.assertEqual(preview.read(str(self.edition.pk))["body"], self.edition.body)
            self.publication_decide(subject="admin", action="WITHDRAW")
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(str(self.edition.pk))
        self.assertEqual(
            list(self.edition.actions.order_by("pk").values_list("subject_id", flat=True)),
            ["operator", "admin", "admin"],
        )
        self.assertEqual(self.immutable_publication_sources(), self.publication_originals)
        mufti = editorial.desk(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(mufti["editions"][0]["state"], "WITHDRAWN")

    def test_publication_grants_never_grant_original_answer_or_free_body_edit(self):
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common,
                case_id=self.target["case_id"],
                text="لا صلاحية علمية",
                expected_revision=3,
                expected_evidence_version=1,
            )
        with self.assertRaises(cases.CaseConflict):
            editorial.create_edition(
                **self.common,
                case_id=self.target["case_id"],
                title="تغيير",
                category="تغيير",
                body="تحرير حر غير مخول",
                expected_revision=3,
                expected_evidence_version=1,
            )
        self.assertEqual(PublicationEdition.objects.count(), 1)
        self.assertEqual(self.state(), self.originals)

    def test_read_review_approve_withdraw_and_domain_authorities_are_independent(self):
        self.authority.revoke(action="REVIEW_PUBLICATION_EDITION")
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide()
        with publication.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertNotIn("REVIEW", result["editions"][0]["options"])
        self.publication_decide(subject="admin")
        self.publication_domain.denied.add(("operator", "APPROVE"))
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide(action="APPROVE")
        self.publication_domain.denied.clear()
        self.authority.revoke(action="APPROVE_PUBLICATION_EDITION")
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide(action="APPROVE")
        self.authority.revoke(action="READ_PUBLICATION_EDITION")
        with publication.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["editions"], [])
        self.assertEqual(self.immutable_publication_sources(), self.publication_originals)

    def test_creator_reviewer_and_scholarly_approver_cannot_self_approve_publication(self):
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide(subject="mufti")
        self.publication_decide()
        for subject in ("operator", "mufti"):
            with self.subTest(subject=subject), self.assertRaises(cases.CaseConflict):
                self.publication_decide(subject=subject, action="APPROVE")
        self.assertEqual(PublicationAction.objects.count(), 1)
        self.publication_decide(subject="admin", action="APPROVE")

    def test_default_flags_missing_and_unversioned_policy_close_manager(self):
        class Unversioned(PublicationAuthority):
            def permits(self, **values):
                return True

        for name, value in (
            ("FATWA_OPERATIONAL_PUBLICATION_ENABLED", False),
            ("FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False),
            ("FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None),
            ("FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", Unversioned()),
        ):
            with (
                self.subTest(name=name),
                override_settings(**{name: value}),
                self.assertRaises(cases.CaseConflict),
            ):
                self.publication_decide()
        for key in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                self.publication_decide(case_ref=self.receipts[key]["public_ref"])
        self.assertEqual(self.state(), self.originals)

    def test_exact_hash_cas_confirmation_and_duplicate_action_do_not_append(self):
        for changes in (
            {"content_sha256": "0" * 64},
            {"expected_actions": 1},
            {"expected_revision": 2},
            {"expected_evidence_version": 2},
            {"confirmed": False},
            {"action": "EDIT"},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.publication_decide(**changes)
        values = self.decision_values()
        self.publication_decide()
        with self.assertRaises(cases.CaseConflict):
            with publication.decide(**self.common, **values):
                pass
        self.assertEqual(PublicationAction.objects.count(), 1)

    def test_newer_edition_prevents_old_review_but_historical_withdrawal_remains(self):
        row = editorial.create_edition(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            title="نسخة أحدث جهزها المفتي",
            category="تصحيح",
            body="نص محرر أحدث مستقل عن الأصل",
            expected_revision=3,
            expected_evidence_version=1,
            synthetic_fixtures_only=True,
        )
        new = PublicationEdition.objects.get(pk=row["id"])
        grant_publication(self.authority, self.publication_domain, self.target, [new])
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide()
        self.publication_decide(action="WITHDRAW")
        self.publication_decide(edition=new)
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.assertEqual(list(self.edition.actions.values_list("action", flat=True)), ["WITHDRAW"])

    def test_current_canonical_author_remains_mufti_even_with_true_publication_grants(self):
        self.publication_decide()
        self.directory.identities["mufti"] = replace(
            self.directory.identities["mufti"], role="ORGANIZER_ADMIN"
        )
        with self.assertRaises(cases.CaseConflict):
            self.publication_decide(subject="admin", action="APPROVE")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        result = self.publication_decide(subject="admin", action="WITHDRAW")
        self.assertEqual(result["editions"][0]["state"], "WITHDRAWN")

    def test_late_revocation_and_equal_epoch_replacement_roll_back_real_action(self):
        original = settings.FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY
        try:
            with self.assertRaises(cases.CaseConflict):
                with publication.decide(**self.common, **self.decision_values()):
                    changed = PublicationDomainAuthority()
                    changed.rules = set(original.rules)
                    settings.FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY = changed
        finally:
            settings.FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY = original
        self.assertEqual(self.state(), self.originals)
        with self.assertRaises(cases.CaseConflict):
            with publication.decide(**self.common, **self.decision_values()):
                self.publication_domain.denied.add(("operator", "REVIEW"))
        self.assertEqual(self.state(), self.originals)

    def test_unrelated_metadata_append_is_not_adopted_as_publication_action(self):
        original = editorial._append_action_locked

        def append_and_change(**kwargs):
            result = original(**kwargs)
            organization.save(
                case_id=self.target["case_id"],
                subject_id="mufti",
                provider=self.directory,
                tags=[],
                question_types=[],
                note="تغيير جانبي",
                command_id=self.save_values()["command_id"],
                expected_metadata_version=0,
                expected_revision=3,
                expected_evidence_version=1,
                synthetic_fixtures_only=True,
            )
            return result

        with (
            patch.object(editorial, "_append_action_locked", append_and_change),
            self.assertRaises(cases.CaseConflict),
        ):
            self.publication_decide()
        self.assertEqual(self.state(), self.originals)

    def login(self, subject):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get(BASE + "login/")
        self.assertEqual(
            post(client, BASE + "login/", {"credential": CREDENTIALS[subject]}, page).status_code,
            303,
        )
        page = client.get(BASE)
        self.assertContains(page, 'id="ops-publication-index"')
        page = post(
            client,
            BASE,
            {"action": "publication_manager", "case_ref": self.target["public_ref"]},
            page,
        )
        self.assertEqual(page.status_code, 200)
        return client, page

    def test_native_review_approval_forms_and_render_revocation_keep_history(self):
        operator, page = self.login("operator")
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "edition_id",
                "content_sha256",
                "sequence",
                "revision",
                "evidence_version",
            )
        }
        data = {**fields, "action": "publication_decide", "decision": "REVIEW", "confirmed": "yes"}
        self.assertEqual(operator.post(BASE, data).status_code, 403)
        self.assertEqual(
            post(operator, BASE, {**data, "body": "تعديل غير مخول"}, page).status_code, 409
        )
        reviewed = post(operator, BASE, data, page)
        self.assertContains(reviewed, 'id="ops-publication-saved"')
        admin, page = self.login("admin")
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "edition_id",
                "content_sha256",
                "sequence",
                "revision",
                "evidence_version",
            )
        }
        data = {**fields, "action": "publication_decide", "decision": "APPROVE", "confirmed": "yes"}
        render = views.render

        def render_and_revoke(*args, **kwargs):
            result = render(*args, **kwargs)
            self.authority.revoke(subject="admin", action="APPROVE_PUBLICATION_EDITION")
            return result

        with patch.object(views, "render", side_effect=render_and_revoke):
            response = post(admin, BASE, data, page)
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, self.edition.body, status_code=409)
        self.assertEqual(list(self.edition.actions.values_list("action", flat=True)), ["REVIEW"])
