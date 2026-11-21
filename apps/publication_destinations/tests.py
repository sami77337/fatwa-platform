"""Native PostgreSQL proof of independent destinations and exact retained sources."""

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseSource
from apps.delivery_queue.models import (
    DeliveryAuditEvent,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
)
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.experimental_publication.tests_ui import Forms
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.research_library import services as library
from apps.source_rights import services as rights
from tests.casework.test_http import post

from . import services, views
from .boundary import history
from .models import DestinationEvent, DestinationRecord, DestinationVersion
from .test_support import FEATURES, PROFILES, Fixture


def originals():
    return tuple(
        list(model.objects.order_by("pk").values())
        for model in (
            Case,
            CaseSource,
            AnswerRevision,
            CaseDecision,
            CaseEvent,
            PublicationEdition,
            PublicationAction,
            DeliveryIntent,
            DeliveryAuditEvent,
            ProviderReceipt,
            ProviderSignatureEvidence,
        )
    )


def form(page, action, *, version=None, command=None):
    return next(
        item
        for item in Forms(page.content.decode()).forms
        if item.get("action") == action
        and (version is None or item.get("version_id") == str(version.pk))
        and (command is None or item.get("command") == command)
    )


@override_settings(**FEATURES)
class DestinationTests(Fixture, TransactionTestCase):
    def test_two_destinations_use_distinct_reviewed_editions_with_independent_signed_outcomes(self):
        self.seed_delivery()
        before = originals()
        website = self.prepare(self.select())
        channel = self.prepare(self.select("TELEGRAM_CHANNEL", self.second))
        self.observe(website, "ACCEPTED")
        accepted = self.read()["records"][0]
        self.assertIsNone(accepted["current_published"])
        self.assertEqual(accepted["versions"][0]["state"], "ACCEPTED")
        self.observe(website)
        self.observe(channel, "FAILED")
        first, second = self.read()["records"]
        self.assertEqual(first["current_published"]["copy"]["body"], self.first.body)
        self.assertIsNone(second["current_published"])
        self.assertEqual(second["versions"][0]["state"], "FAILED")
        self.assertEqual(second["versions"][0]["copy"]["body"], self.second.body)
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(
            first["versions"][0]["plan_sha256"], second["versions"][0]["plan_sha256"]
        )
        self.assertFalse(first["current_published"]["external_publication_verified"])
        self.assertEqual(before, originals())
        self.assertEqual(
            (
                DestinationRecord.objects.count(),
                DestinationVersion.objects.count(),
                DestinationEvent.objects.count(),
            ),
            (2, 2, 9),
        )
        # Global library semantics deliberately continue to expose only edition 2.
        item = self.second.citations[0]
        policy = PreviewPolicy(
            tuple(
                PublicationGrant(str(row.pk), row.content_sha256)
                for row in (self.first, self.second)
            ),
            (ReferenceGrant(self.catalog_id, 2, item["source_sha256"]),),
            timezone.now() + timedelta(minutes=20),
            True,
        )
        with override_settings(
            FATWA_LIBRARY_PREVIEW_ENABLED=True,
            FATWA_LIBRARY_PREVIEW_POLICY=policy,
            FATWA_KNOWLEDGE_LINKS_ENABLED=True,
        ):
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(str(self.first.pk))
            self.assertEqual(preview.read(str(self.second.pk))["body"], self.second.body)

    def test_new_candidate_failure_and_withdrawal_do_not_replace_other_destination_or_resurrect_old(
        self,
    ):
        website = self.prepare(self.select())
        channel = self.prepare(self.select("TELEGRAM_CHANNEL", self.second))
        self.observe(website)
        self.observe(channel)
        corrected = self.edition("نسخة موقع ثالثة راجعها أشخاص مستقلون.")
        second = self.select(source=corrected, expected_version=1)
        self.assertEqual(self.read()["records"][0]["current_published"]["id"], str(website.pk))
        self.observe(self.prepare(second), "FAILED")
        self.assertEqual(self.read()["records"][0]["current_published"]["id"], str(website.pk))
        third = self.select(source=corrected, expected_version=2)
        self.observe(self.prepare(third))
        self.decide(third, "WITHDRAW")
        current = self.read()["records"]
        self.assertIsNone(current[0]["current_published"])
        self.assertEqual(current[1]["current_published"]["id"], str(channel.pk))
        self.assertEqual(
            [row["state"] for row in current[0]["versions"]],
            ["WITHDRAW", "FAILED", "SIMULATED_PUBLISHED"],
        )
        self.assertEqual(DestinationVersion.objects.filter(record=website.record).count(), 3)
        self.assertTrue(website.events.filter(action="SIMULATED_PUBLISHED").exists())

    def test_exact_source_withdrawal_isolated_and_current_rights_and_canonical_change_hide_both(
        self,
    ):
        website = self.prepare(self.select())
        channel = self.prepare(self.select("TELEGRAM_CHANNEL", self.second))
        self.observe(website)
        self.observe(channel)
        before = history(self.common["case_id"])
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=str(self.first.pk),
            action="WITHDRAW",
        )
        rows = self.read()["records"]
        self.assertIsNone(rows[0]["current_published"])
        self.assertIsNone(rows[0]["versions"][0]["copy"])
        self.assertEqual(rows[1]["current_published"]["copy"]["body"], self.second.body)
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.rights_revision["id"],
            action="REVOKE",
            confirmed=True,
            note="Current source right withdrawn",
        )
        self.assertTrue(all(row["current_published"] is None for row in self.read()["records"]))
        self.assertEqual(before, history(self.common["case_id"]))
        # Even a source-free replacement must have its own new independently approved edition.
        cases.add_followup(
            token=self.receipt["token"],
            text="A changed synthetic material fact",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.select("TELEGRAM_CHANNEL", self.second, expected_version=1)
        self.assertEqual(before, history(self.common["case_id"]))

    def test_selection_requires_exact_approved_source_capability_and_independent_destination_decisions(
        self,
    ):
        pending = publication.create_edition(
            **self.common,
            **self.pins(),
            title="Unreviewed synthetic",
            category="Synthetic",
            body="Never approved",
        )
        with self.assertRaises(cases.CaseConflict):
            self.select(source=PublicationEdition.objects.get(pk=pending["id"]))
        for changes in (
            {"source_selection": str(self.first.pk)},
            {"destination": "UNCONFIGURED"},
            {"confirmed": 1},
            {"expected_version": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.select(**changes)
        with override_settings(
            FATWA_PUBLICATION_DESTINATION_PROFILES=(replace(PROFILES[0], max_chars=1),)
        ):
            with self.assertRaises(cases.CaseConflict):
                self.select()
        row = self.select()
        for command, subject in (
            ("REVIEW", "editor"),
            ("APPROVE", "publisher"),
            ("PREPARE", "publisher"),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.decide(row, command, subject)
        row = self.decide(row, "REVIEW")
        for subject in ("other", "editor"):
            with self.assertRaises(cases.CaseConflict):
                self.decide(row, "APPROVE", subject)
        row = self.decide(row, "APPROVE")
        self.decide(row, "PREPARE")
        self.assertEqual(row.events.count(), 3)

    def test_signed_outcomes_bind_every_plan_source_destination_and_preparation_and_current_key(
        self,
    ):
        row = self.prepare(self.select())
        other = self.prepare(self.select("TELEGRAM_CHANNEL", self.second))
        changes = (
            {"record_id": str(other.record_id)},
            {"version_id": str(other.pk)},
            {"source_id": str(self.second.pk)},
            {"source_sha256": self.second.content_sha256},
            {"destination": "TELEGRAM_CHANNEL"},
            {"plan_sha256": "a" * 64},
            {"profile_sha256": "b" * 64},
            {"version_sha256": "c" * 64},
            {"preparation_sha256": "d" * 64},
            {"preparation_id": str(uuid.uuid4())},
            {"key_id": "unknown-key"},
            {"issuer": "untrusted-issuer"},
            {
                "issued_at": (timezone.now() - timedelta(hours=1)).isoformat(),
                "expires_at": (timezone.now() - timedelta(minutes=50)).isoformat(),
            },
        )
        before = history(self.common["case_id"])
        for change in changes:
            with self.subTest(change=change), self.assertRaises(cases.CaseConflict):
                self.observe(row, envelope=self.signed(row, **change))
        signed = self.signed(row)
        for envelope in (
            {**signed, "signature_b64url": "x" * 86},
            {**signed, "public_key": self.signer.public_key().public_bytes_raw().hex()},
            {**signed, "verified": True},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.observe(row, envelope=envelope)
        self.verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        with self.assertRaises(cases.CaseConflict):
            self.observe(row, envelope=signed)
        self.assertEqual(before, history(self.common["case_id"]))

    def test_cas_and_exact_request_idempotency_preserve_single_history(self):
        key = uuid.uuid4()
        first = self.select(request_key=key)
        self.assertEqual(first.pk, self.select(request_key=key).pk)
        with self.assertRaises(cases.CaseConflict):
            self.select(request_key=key, source=self.second)
        self.prepare(first)
        envelope, request_key = self.signed(first), uuid.uuid4()
        self.observe(first, envelope=envelope, request_key=request_key, expected_events=3)
        self.observe(first, envelope=envelope, request_key=request_key, expected_events=3)
        with self.assertRaises(cases.CaseConflict):
            self.observe(first, envelope=envelope)
        before = history(self.common["case_id"])
        with self.assertRaises(cases.CaseConflict):
            self.select(source=self.second, expected_version=0)
        with self.assertRaises(cases.CaseConflict):
            self.observe(first)
        self.assertEqual(before, history(self.common["case_id"]))

    def test_concurrent_selection_has_one_cas_winner(self):
        def contender():
            connections.close_all()
            try:
                return str(self.select().pk)
            except cases.CaseConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda _: contender(), (1, 2)))
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(DestinationVersion.objects.count(), 1)
        self.assertEqual(DestinationRecord.objects.count(), 1)

    def test_sql_sealed_writes_cannot_forge_source_plan_state_or_mutate_history(self):
        row = self.select()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DestinationVersion.objects.filter(pk=row.pk).update(note="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            DestinationRecord.objects.filter(pk=row.record_id).delete()
        for mutate in (
            lambda candidate: setattr(
                candidate, "source_pins", {**candidate.source_pins, "sha256": "a" * 64}
            ),
            lambda candidate: setattr(candidate, "previous_digest", "b" * 64),
            lambda candidate: setattr(candidate, "plan_payload", row.plan_payload),
        ):
            candidate = copy.copy(row)
            candidate.id, candidate.request_key = uuid.uuid4(), uuid.uuid4()
            candidate.number, candidate.previous_digest = 2, row.digest
            plan = services._plan(
                candidate, json.loads(candidate.profile_payload), candidate.source_pins
            )
            candidate.plan_payload = json.dumps(
                plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            candidate.plan_sha256 = services.profiles.fingerprint(plan)
            mutate(candidate)
            with self.assertRaises(IntegrityError), transaction.atomic():
                library._seal(candidate)
        event = DestinationEvent(
            version=row,
            sequence=1,
            previous_digest=row.digest,
            action="APPROVE",
            plan_sha256=row.plan_sha256,
            case_revision=3,
            evidence_version=1,
            request_key=uuid.uuid4(),
            request_sha256="e" * 64,
            provider_id=self.directory.provider_id,
            subject_id="publisher",
            auth_epoch="epoch-1",
            note="Forged transition",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            library._seal(event)
        self.assertEqual(DestinationVersion.objects.count(), 1)
        self.assertEqual(DestinationEvent.objects.count(), 0)

    def test_current_identity_authority_profile_signature_trust_and_finite_grants_are_required(
        self,
    ):
        row = self.prepare(self.select())
        self.observe(row)
        for flag in (False, 1):
            with (
                override_settings(FATWA_PUBLICATION_DESTINATIONS_ENABLED=flag),
                self.assertRaises(cases.CaseConflict),
            ):
                self.read()
        for name in (
            "FATWA_PUBLICATION_DESTINATIONS_AUTHORITY",
            "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY",
            "FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER",
            "FATWA_CASEWORK_IDENTITY_PROVIDER",
        ):
            with override_settings(**{name: None}), self.assertRaises(cases.CaseConflict):
                self.read()
        with override_settings(
            FATWA_PUBLICATION_DESTINATION_PROFILES=(
                replace(PROFILES[0], revision="site.v2"),
                PROFILES[1],
            )
        ):
            self.assertIsNone(self.read()["records"][0]["current_published"])
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], auth_epoch="epoch-2"
        )
        self.assertIsNone(self.read()["records"][0]["current_published"])
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], auth_epoch="epoch-1"
        )
        self.verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        self.assertIsNone(self.read()["records"][0]["current_published"])
        self.verifier._revoked_ids = frozenset()
        self.authority.until = timezone.now() + timedelta(hours=2)
        with self.assertRaises(cases.CaseConflict):
            self.read()

    def test_late_policy_source_profile_or_key_change_discards_render_and_rolls_back_selection(
        self,
    ):
        client, page = self.login()
        page = self.open(client, page)
        data = {
            **form(page, "pd_select"),
            "source_selection": services.selection(self.first),
            "note": "Exact reviewed edition",
            "confirmed": "yes",
        }
        render = views.render
        before = history(self.common["case_id"])

        def revoke(*args, **kwargs):
            result = render(*args, **kwargs)
            self.authority.denied.add("READ")
            return result

        with patch.object(views, "render", side_effect=revoke):
            result = post(client, "/casework/staff/", data, page)
        self.assertEqual(result.status_code, 409)
        self.assertNotContains(result, self.first.body, status_code=409)
        self.assertEqual(before, history(self.common["case_id"]))
        self.authority.denied.clear()

        def source_revoke(*args, **kwargs):
            result = render(*args, **kwargs)
            rights.review(
                **{**self.common, "subject_id": "publisher"},
                revision_id=self.rights_revision["id"],
                action="REVOKE",
                confirmed=True,
                note="Revoked during render",
            )
            return result

        with patch.object(views, "render", side_effect=source_revoke):
            result = post(client, "/casework/staff/", data, page)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(before, history(self.common["case_id"]))

    def test_native_forms_review_each_exact_copy_and_never_accept_url_key_or_fabricated_success(
        self,
    ):
        editor, page = self.login()
        page = self.open(editor, page)
        data = {
            **form(page, "pd_select"),
            "source_selection": services.selection(self.first),
            "note": "Native exact source selection",
            "confirmed": "yes",
        }
        for field in ("public_url", "public_key", "verified"):
            self.assertEqual(
                post(
                    editor,
                    "/casework/staff/",
                    {**data, field: "https://127.0.0.1/library-preview/"},
                    page,
                ).status_code,
                400,
            )
        page = post(editor, "/casework/staff/", data, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, self.first.body)
        self.assertNotContains(page, "PRIVATE SYNTHETIC")
        row = DestinationVersion.objects.get()
        reviewer, review_page = self.login("other")
        review_page = self.open(reviewer, review_page)
        review_page = post(
            reviewer,
            "/casework/staff/",
            {
                **form(review_page, "pd_decide", version=row, command="REVIEW"),
                "note": "Native independent review",
                "confirmed": "yes",
            },
            review_page,
        )
        self.assertEqual(review_page.status_code, 200, review_page.content)
        publisher, page = self.login("publisher")
        page = self.open(publisher, page)
        for command in ("APPROVE", "PREPARE"):
            page = post(
                publisher,
                "/casework/staff/",
                {
                    **form(page, "pd_decide", version=row, command=command),
                    "note": "Native explicit decision",
                    "confirmed": "yes",
                },
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
        data = {
            **form(page, "pd_provider_event", version=row),
            "note": "Native signed outcome",
            "confirmed": "yes",
        }
        bad = post(
            publisher,
            "/casework/staff/",
            {**data, "envelope": json.dumps({"reported": "PUBLISHED", "verified": True})},
            page,
        )
        self.assertEqual(bad.status_code, 409)
        page = post(
            publisher, "/casework/staff/", {**data, "envelope": json.dumps(self.signed(row))}, page
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "ليست نشرًا فعليًا")
        self.assertContains(page, 'data-external-publication-verified="false"')
        self.assertNotContains(page, 'name="public_url"')
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.assertEqual(row.events.count(), 4)
