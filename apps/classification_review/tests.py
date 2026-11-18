"""Synthetic PostgreSQL proof; reuse the existing canonical publication/source fixture."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication import services as publications
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeAction
from apps.knowledge_links.tests import FEATURES as KNOWLEDGE_FEATURES
from apps.knowledge_links.tests import Fixture as KnowledgeFixture
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .authority import ClassificationAuthority
from .models import ClassificationAction, ClassificationRevision

FEATURES = {**KNOWLEDGE_FEATURES, "FATWA_CLASSIFICATION_REVIEW_ENABLED": True}


class Authority(ClassificationAuthority):
    def __init__(self, ref):
        self.ref = ref

    def permits(self, **kwargs):
        return (
            kwargs["case_ref"] == self.ref
            and kwargs["auth_epoch"] == "epoch-1"
            and (
                kwargs["action"] in {"VIEW", "PROPOSE"}
                or kwargs["subject_id"] in {"publisher", "other"}
            )
        )


class Fixture(KnowledgeFixture):
    def setUp(self):
        super().setUp()
        self.source = KnowledgeFixture.propose(self)
        KnowledgeFixture.approve(self, self.source)
        self.classification_authority = Authority(self.receipt["public_ref"])
        policy = override_settings(
            FATWA_CLASSIFICATION_REVIEW_AUTHORITY=self.classification_authority
        )
        policy.enable()
        self.addCleanup(policy.disable)

    def proposal(self, **kwargs):
        return services.propose(
            **self.access,
            knowledge_id=self.source["id"],
            label="تصنيف تجريبي مقترح",
            reason="PRIVATE classification reason",
            **kwargs,
        )

    def decision(self, row, action="APPROVE", **kwargs):
        return services.act(
            **{**self.access, "subject_id": "publisher", **kwargs},
            revision_id=row["id"],
            action=action,
            note="PRIVATE human decision",
            confirmed=True,
        )

    def desk(self, **kwargs):
        return services.desk(**self.access, **kwargs)


@override_settings(**FEATURES)
class ClassificationTests(Fixture, TransactionTestCase):
    def test_proposed_until_independent_human_no_canonical_mutation(self):
        before = publications.library(
            **{k: v for k, v in self.access.items() if k != "publication_id"}
        )
        source_actions = KnowledgeAction.objects.count()
        row = self.proposal()
        self.assertEqual(row["state"], "PROPOSED")
        self.assertFalse(self.desk()["history"][0]["effective"])
        self.assertEqual(ClassificationAction.objects.count(), 0)
        with self.assertRaises(cases.CaseConflict):
            self.decision(row, subject_id="editor")
        self.decision(row)
        self.assertTrue(self.desk()["history"][0]["effective"])
        self.assertEqual(
            before,
            publications.library(**{k: v for k, v in self.access.items() if k != "publication_id"}),
        )
        self.assertEqual(KnowledgeAction.objects.count(), source_actions)
        self.assertNotIn("classification", str(before))

    def test_default_deny_scope_role_and_recheck(self):
        row = self.proposal()
        with override_settings(FATWA_CLASSIFICATION_REVIEW_AUTHORITY=None):
            for operation in (self.proposal, self.desk, lambda: self.decision(row)):
                with self.assertRaises(cases.CaseConflict):
                    operation()
        for change in (
            dict(case_keys=frozenset()),
            dict(role="ORGANIZER_ADMIN"),
            dict(active=False),
        ):
            original = self.directory.identities["publisher"]
            self.directory.identities["publisher"] = replace(original, **change)
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
            self.directory.identities["publisher"] = original
        original_permit = self.classification_authority.permits

        def revoke(**kwargs):
            permitted = original_permit(**kwargs)
            self.directory.identities["publisher"] = replace(
                self.directory.identities["publisher"], auth_epoch="changed"
            )
            return permitted

        with patch.object(self.classification_authority, "permits", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
        self.assertEqual(ClassificationAction.objects.count(), 0)

    def test_reject_correction_and_withdrawal_never_reapprove(self):
        first = self.proposal()
        self.decision(first, "REJECT")
        with self.assertRaises(cases.CaseConflict):
            self.decision(first)
        second = self.proposal(replaces_id=first["id"])
        self.assertEqual(second["number"], 2)
        self.assertFalse(any(row["effective"] for row in self.desk()["history"]))
        self.decision(second)
        third = self.proposal(replaces_id=second["id"])
        self.assertFalse(any(row["effective"] for row in self.desk()["history"]))
        with self.assertRaises(cases.CaseConflict):
            self.decision(second, "WITHDRAW")
        self.decision(third, "WITHDRAW")
        with self.assertRaises(cases.CaseConflict):
            self.decision(third)
        self.assertEqual(len(self.desk()["history"]), 3)

    def test_source_correction_hides_and_blocks_then_withdraws(self):
        row = self.proposal()
        self.decision(row)
        KnowledgeFixture.propose(self, replaces_id=self.source["id"])
        history = self.desk()["history"][0]
        self.assertFalse(history["available"])
        self.assertFalse(history["effective"])
        self.assertEqual(history["reason"], "")
        self.assertNotIn("note", str(history["actions"]))
        self.decision(row, "WITHDRAW")

    def test_publication_version_and_source_pin_change_block_decisions(self):
        row = self.proposal()
        original_target = knowledge._target

        def changed(*args, **kwargs):
            snapshot, heading, transcript = original_target(*args, **kwargs)
            return {**snapshot, "source_sha256": "0" * 64}, heading, transcript

        with patch.object(knowledge, "_target", side_effect=changed):
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
            self.assertFalse(self.desk()["history"][0]["available"])
        self.new_publication()
        with self.assertRaises(cases.CaseConflict):
            self.decision(row)
        self.decision(row, "WITHDRAW")
        audit = self.desk(history=True)
        self.assertNotIn("PRIVATE", str(audit))
        self.assertNotIn(self.heading.title_original, str(audit))

    def test_rights_loss_hides_labels_reasons_sources_and_decision_notes(self):
        row = self.proposal()
        self.decision(row)
        original = knowledge._row_permitted
        with patch.object(
            knowledge,
            "_row_permitted",
            side_effect=lambda c, r, u: False if u == "READ" else original(c, r, u),
        ):
            result = self.desk()
            self.assertEqual(result["candidates"], [])
            self.assertNotIn("PRIVATE", str(result))
            self.assertFalse(result["history"][0]["effective"])
        publications.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=self.edition["id"],
            action="WITHDRAW",
        )
        self.decision(row, "WITHDRAW")
        self.assertNotIn("PRIVATE", str(self.desk(history=True)))

    def test_two_concurrent_conflicting_human_decisions(self):
        row = self.proposal()
        barrier = Barrier(2)

        def decide(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                self.decision(row, action)
                return "accepted"
            except cases.CaseConflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(decide, ["APPROVE", "REJECT"]))
        self.assertCountEqual(results, ["accepted", "conflict"])
        self.assertEqual(ClassificationAction.objects.count(), 1)

    def test_database_append_only_self_review_and_exclusive_decision(self):
        row = self.proposal()
        revision = ClassificationRevision.objects.get(pk=row["id"])
        for operation in (
            lambda: ClassificationRevision.objects.filter(pk=revision.pk).update(label="erase"),
            lambda: ClassificationRevision.objects.filter(pk=revision.pk).delete(),
            lambda: ClassificationAction.objects.create(
                revision=revision,
                action="APPROVE",
                note="self",
                subject_id=revision.subject_id,
                provider_id=revision.provider_id,
                auth_epoch=revision.auth_epoch,
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.decision(row)
        for operation in (
            lambda: ClassificationAction.objects.all().update(note="erase"),
            lambda: ClassificationAction.objects.all().delete(),
            lambda: ClassificationAction.objects.create(
                revision=revision,
                action="REJECT",
                note="conflict",
                subject_id="other",
                provider_id=revision.provider_id,
                auth_epoch=revision.auth_epoch,
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.classification_review.urls"})
    def test_http_closed_strict_csrf_and_private_projection(self):
        row = self.proposal()
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        fields = dict(action="classification_desk", publication_id=self.edition["id"])
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
            page = client.get("/casework/staff/login/")
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                page,
            )
            page = client.get("/casework/staff/")
            page = post(client, "/casework/staff/", fields, page)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "PROPOSED")
            self.assertNotContains(page, 'value="classification_approve"')
            self.assertContains(page, "فهرس")
            self.assertIn("no-store", page["Cache-Control"])
            self.assertEqual(
                post(
                    client, "/casework/staff/", {**fields, "subject_id": "publisher"}, page
                ).status_code,
                400,
            )
            denied = post(
                client,
                "/casework/staff/",
                dict(
                    action="classification_approve",
                    publication_id=self.edition["id"],
                    revision_id=row["id"],
                    note="self review",
                    confirm="yes",
                ),
                page,
            )
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(b"PRIVATE", denied.content)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], case_keys=frozenset()
            )
            denied = post(client, "/casework/staff/", fields, page)
            self.assertEqual(denied.status_code, 403)
            self.assertNotIn(b"PRIVATE", denied.content)

    def test_closed_flags_confirmation_and_unreviewed_source(self):
        row = self.proposal()
        with override_settings(FATWA_CLASSIFICATION_REVIEW_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.proposal()
        with self.assertRaises(cases.CaseConflict):
            services.act(
                **{**self.access, "subject_id": "publisher"},
                revision_id=row["id"],
                action="APPROVE",
                note="manual",
                confirmed=False,
            )
        pending = KnowledgeFixture.propose(self)
        with self.assertRaises(cases.CaseConflict):
            services.propose(
                **self.access,
                knowledge_id=pending["id"],
                label="pending source",
                reason="not approved",
            )
        self.assertEqual(ClassificationAction.objects.count(), 0)

    def test_late_authority_revocation_rolls_back_written_decision(self):
        row = self.proposal()
        with patch.object(self.classification_authority, "permits", side_effect=[True, False]):
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
        self.assertEqual(ClassificationAction.objects.count(), 0)
        self.assertEqual(self.desk()["history"][0]["state"], "PROPOSED")

    def test_cross_publication_ids_never_authorize(self):
        row = self.proposal()
        replacement = self.new_publication()
        with self.assertRaises(cases.CaseConflict):
            services.act(
                **{**self.access, "publication_id": replacement["id"], "subject_id": "publisher"},
                revision_id=row["id"],
                action="APPROVE",
                note="wrong edition",
                confirmed=True,
            )
        with self.assertRaises(cases.CaseConflict):
            services.propose(
                **{**self.access, "publication_id": replacement["id"]},
                knowledge_id=self.source["id"],
                label="wrong edition",
                reason="denied",
            )
        self.assertEqual(ClassificationAction.objects.count(), 0)

    def test_real_rights_expiry_revocation_and_redacted_history(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.source_rights import services as rights
        from apps.source_rights.tests import Authority as RightsAuthority

        with override_settings(
            FATWA_SOURCE_RIGHTS_ENABLED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
        ):
            source = rights.register(**self.common, kind="TOC_METADATA", target_id=self.heading.pk)
            grant = rights.propose(
                **self.common,
                source_id=source["id"],
                expected_number=0,
                uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
                basis="Synthetic rights evidence",
                note="review source",
                ttl_minutes=1,
            )
            review = {**self.common, "subject_id": "publisher"}
            rights.review(
                **review,
                revision_id=grant["id"],
                action="APPROVE",
                confirmed=True,
                note="independent synthetic rights decision",
            )
            with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True):
                row = self.proposal()
                self.decision(row)
                self.assertTrue(self.desk()["history"][0]["effective"])
                with patch.object(
                    rights.timezone, "now", return_value=timezone.now() + timedelta(minutes=2)
                ):
                    with self.assertRaises(cases.CaseConflict):
                        self.desk()
                    self.assertNotIn("PRIVATE", str(self.desk(history=True)))
                rights.review(
                    **review,
                    revision_id=grant["id"],
                    action="REVOKE",
                    confirmed=True,
                    note="synthetic revocation",
                )
                with self.assertRaises(cases.CaseConflict):
                    self.desk()
                self.decision(row, "WITHDRAW")
                self.assertEqual(self.desk(history=True)["history"][0]["state"], "WITHDRAWN")
