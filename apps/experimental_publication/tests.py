"""Synthetic PostgreSQL tests for publication boundaries and independent approvals."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .authority import PublicationAuthority
from .models import PublicationAction, PublicationEdition


class Directory(MuftiIdentityProvider):
    provider_id = "synthetic-publication-directory"

    def __init__(self, refs):
        self.identities = {
            subject: MuftiIdentity(
                subject,
                "MUFTI",
                True,
                frozenset(refs),
                "epoch-1",
                timezone.now() + timedelta(minutes=30),
            )
            for subject in ("editor", "publisher", "other")
        }

    def resolve(self, subject_id):
        return self.identities.get(subject_id)

    def authenticate(self, credential):
        return (
            self.resolve("editor")
            if credential == "synthetic-editor-credential-32-characters"
            else None
        )


class Authority(PublicationAuthority):
    def __init__(self, ref, subject="publisher"):
        self.ref, self.subject = ref, subject

    def permits(self, **kwargs):
        return (
            kwargs["subject_id"] == self.subject
            and kwargs["case_ref"] == self.ref
            and kwargs["auth_epoch"] == "epoch-1"
        )


@override_settings(FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True)
class PublicationTests(TransactionTestCase):
    def setUp(self):
        self.receipt = cases.intake_case(
            original_question="PRIVATE QUESTION requester@example.test",
            source_event_id="publication-website",
            requester_id="private-requester",
            idempotency_key="publication-intake",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.common = {
            "case_id": self.receipt["case_id"],
            "subject_id": "editor",
            "provider": self.directory,
            "synthetic_fixtures_only": True,
        }
        draft = cases.save_answer(
            **self.common,
            expected_revision=1,
            expected_evidence_version=1,
            text="Original approved synthetic answer PRIVATE DETAIL",
        )
        self.answer_id = draft["answers"][-1]["id"]
        cases.record_decision(
            **self.common,
            answer_id=self.answer_id,
            expected_revision=2,
            expected_evidence_version=1,
            action="APPROVE",
            note="PRIVATE AUDIT",
        )
        self.policy = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(self.receipt["public_ref"])
        )
        self.policy.enable()
        self.addCleanup(self.policy.disable)

    def edition(self, **kwargs):
        case = Case.objects.get(pk=self.common["case_id"])
        arguments = dict(
            self.common,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            title="عنوان تجريبي",
            category="تصنيف تجريبي",
            body="نص محرر بلا بيانات شخصية",
        )
        arguments.update(kwargs)
        return services.create_edition(**arguments)

    def act(self, edition, action, subject="editor", **kwargs):
        return services.act(
            **{**self.common, "subject_id": subject},
            edition_id=edition["id"],
            action=action,
            **kwargs,
        )

    def library(self, query="", subject="editor"):
        return services.library(
            subject_id=subject, provider=self.directory, query=query, synthetic_fixtures_only=True
        )

    def publish(self, edition):
        self.act(edition, "REVIEW", reviewed=True)
        return self.act(edition, "APPROVE", "publisher")

    def test_copy_review_independent_approval_and_no_private_search_leak(self):
        before = list(CaseEvent.objects.values_list("pk", flat=True))
        edition = self.edition()
        self.assertEqual(self.library(), [])
        self.assertEqual(self.library("PRIVATE"), [])
        with self.assertRaisesMessage(cases.CaseConflict, "redaction_review_required"):
            self.act(edition, "APPROVE", "publisher")
        with self.assertRaises(cases.CaseConflict):
            self.act(edition, "REVIEW")
        self.act(edition, "REVIEW", reviewed=True)
        self.assertEqual(self.library(), [])
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(self.receipt["public_ref"], "editor")
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "independent_publication"):
                self.act(edition, "APPROVE")
        self.act(edition, "APPROVE", "publisher")
        result = self.library()
        self.assertEqual(len(result), 1)
        self.assertNotIn("case_id", result[0])
        self.assertNotIn("subject_id", result[0])
        self.assertEqual(self.library("PRIVATE"), [])
        self.assertEqual(len(self.library("نص")), 1)
        self.assertEqual(
            AnswerRevision.objects.get(pk=self.answer_id).text,
            "Original approved synthetic answer PRIVATE DETAIL",
        )
        self.assertEqual(list(CaseEvent.objects.values_list("pk", flat=True)), before)

    def test_default_gate_authority_and_non_mufti_fail_closed(self):
        with override_settings(FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.edition()
            with self.assertRaises(cases.CaseConflict):
                self.library()
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        with override_settings(FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=None):
            with self.assertRaises(cases.CaseConflict):
                self.act(edition, "APPROVE", "publisher")
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], role="ORGANIZER_ADMIN"
        )
        with self.assertRaises(cases.CaseConflict):
            self.act(edition, "APPROVE", "publisher")
        self.assertEqual(self.library(), [])

    def test_new_facts_hide_approved_publication_and_deny_stale_approval(self):
        edition = self.edition()
        self.publish(edition)
        stale = self.edition(body="مرشح خاص لم يعتمد")
        self.act(stale, "REVIEW", reviewed=True)
        cases.add_followup(
            token=self.receipt["token"],
            text="new material facts",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(self.library(), [])
        with self.assertRaises(cases.CaseConflict):
            self.act(stale, "APPROVE", "publisher")
        with self.assertRaises(cases.CaseConflict):
            self.edition()
        self.act(edition, "WITHDRAW", "publisher")

    def test_correction_needs_new_review_and_withdrawal_does_not_resurrect(self):
        first = self.edition()
        self.publish(first)
        second = self.edition(body="تصحيح النسخة المنشورة")
        self.assertEqual(self.library()[0]["id"], first["id"])
        self.publish(second)
        self.assertEqual([e["id"] for e in self.library()], [second["id"]])
        self.act(second, "WITHDRAW", "publisher")
        self.assertEqual(self.library(), [])
        self.assertEqual(PublicationEdition.objects.count(), 2)

    def test_cross_case_foreign_edition_and_scope_denied(self):
        edition = self.edition()
        other = cases.intake_case(
            original_question="other private question",
            source_event_id="other-website",
            requester_id="other-requester",
            idempotency_key="other-intake",
            synthetic_fixtures_only=True,
        )
        for subject, identity in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                identity, case_keys=frozenset([self.receipt["public_ref"], other["public_ref"]])
            )
        with self.assertRaises(cases.CaseConflict):
            services.act(
                **{**self.common, "case_id": other["case_id"]},
                edition_id=edition["id"],
                action="REVIEW",
                reviewed=True,
            )
        self.publish(edition)
        self.directory.identities["other"] = replace(
            self.directory.identities["other"], case_keys=frozenset([other["public_ref"]])
        )
        self.assertEqual(self.library(subject="other"), [])

    def test_immutable_rows_database_source_binding_and_independent_approval(self):
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        for operation in (
            lambda: PublicationEdition.objects.filter(pk=edition["id"]).update(body="changed"),
            lambda: PublicationEdition.objects.filter(pk=edition["id"]).delete(),
            lambda: PublicationAction.objects.all().update(subject_id="changed"),
            lambda: PublicationAction.objects.create(
                edition_id=edition["id"],
                action="APPROVE",
                subject_id="editor",
                provider_id=self.directory.provider_id,
                auth_epoch="epoch-1",
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.assertEqual(PublicationAction.objects.count(), 1)

    def test_new_candidate_invalidates_older_pending_approval(self):
        older = self.edition()
        self.act(older, "REVIEW", reviewed=True)
        self.edition(body="new candidate")
        with self.assertRaisesMessage(cases.CaseConflict, "edition_changed"):
            self.act(older, "APPROVE", "publisher")

    def test_epoch_revocation_during_locked_action_rolls_back(self):
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], auth_epoch="revoked"
        )
        with self.assertRaises(cases.CaseConflict):
            self.act(edition, "APPROVE", "publisher")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())

    def test_changed_citation_and_mid_action_identity_revoke_fail_closed(self):
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        with patch.object(services, "_citation_snapshot", return_value=[{"changed": True}]):
            with self.assertRaisesMessage(cases.CaseConflict, "citation_source_changed"):
                self.act(edition, "APPROVE", "publisher")
        original = self.directory.identities["publisher"]

        class RevokingAuthority(Authority):
            def permits(inner, **kwargs):
                self.directory.identities["publisher"] = replace(original, auth_epoch="revoked")
                return True

        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=RevokingAuthority(self.receipt["public_ref"])
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "identity_changed"):
                self.act(edition, "APPROVE", "publisher")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.experimental_publication.urls"})
    def test_native_forms_csrf_strict_fields_and_closed_library(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            self.assertEqual(
                client.post(
                    "/casework/staff/",
                    {
                        "action": "pub_create",
                        "case_ref": self.receipt["public_ref"],
                    },
                ).status_code,
                403,
            )
            page = client.get("/casework/staff/login/")
            result = post(
                client,
                "/casework/staff/login/",
                {
                    "credential": "synthetic-editor-credential-32-characters",
                },
                page,
            )
            self.assertEqual(result.status_code, 303)
            page = client.get("/casework/staff/")
            page = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_open",
                    "case_ref": self.receipt["public_ref"],
                },
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, 'id="publication-body"')
            fields = {
                "action": "pub_create",
                "case_ref": self.receipt["public_ref"],
                "revision": "3",
                "evidence_version": "1",
                "title": "عنوان تجريبي",
                "category": "تصنيف تجريبي",
                "body": "نص آمن اصطناعي",
            }
            forged = post(client, "/casework/staff/", {**fields, "subject_id": "publisher"}, page)
            self.assertEqual(forged.status_code, 400)
            page = post(client, "/casework/staff/", fields, page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertIn("no-store", page["Cache-Control"])
            self.assertEqual(PublicationEdition.objects.count(), 1)
            page = post(client, "/casework/staff/", {"action": "pub_library", "query": ""}, page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertNotContains(page, "نص آمن اصطناعي")
            self.assertNotContains(page, "PRIVATE")
            self.assertNotContains(page, self.receipt["public_ref"])
            edition = {"id": str(PublicationEdition.objects.get().pk)}
            unpublished = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_read",
                    "edition_id": edition["id"],
                },
                page,
            )
            self.assertEqual(unpublished.status_code, 404)
            self.publish(edition)
            detail = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_read",
                    "edition_id": edition["id"],
                },
                page,
            )
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertContains(detail, "نص آمن اصطناعي")
            self.assertNotContains(detail, "PRIVATE")
            self.assertNotContains(detail, self.receipt["public_ref"])
            self.act(edition, "WITHDRAW", "publisher")
            withdrawn = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_read",
                    "edition_id": edition["id"],
                },
                detail,
            )
            self.assertEqual(withdrawn.status_code, 404)
            self.assertEqual(
                client.get("/casework/staff/", REMOTE_ADDR="192.0.2.2").status_code, 403
            )
