"""Canonical timed-annotation approval/use boundaries on synthetic PostgreSQL."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core import signing
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, PrivateAnswerRelease
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import Case, CaseDecision
from apps.composite_delivery import services as composite
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
from apps.delivery_queue.models import ProviderSignatureEvidence
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority
from apps.knowledge_links import services as knowledge
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.source_rights.tests import Authority as RightsAuthority
from apps.timed_citations import services as timed
from apps.timed_citations.models import TimedCitation, TimedCitationAction
from apps.timed_citations.tests import SETTINGS, Fixture
from apps.timed_citations.views import SALT
from config.settings.campaign_review import MIDDLEWARE as CAMPAIGN_MIDDLEWARE
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import post

FEATURES = {
    **SETTINGS,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    "FATWA_LIBRARY_PREVIEW_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENABLED": True,
}


@override_settings(**FEATURES)
class TimedBindingsTests(Fixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.rights.valid_until = timezone.now() + timedelta(minutes=10)
        self.now = timezone.now()
        self.approval_key = Ed25519PrivateKey.generate()
        self.approval_verifier = Ed25519ApprovalVerifier(
            issuer="synthetic-mufti", audience="synthetic-case-return",
            trusted_public_keys={"mufti-key": self.approval_key.public_key().public_bytes_raw()},
            identity_lookup=lambda subject: IdentityStatus(subject, "MUFTI", True),
            is_revoked_or_consumed=lambda *_: False, clock=lambda: self.now,
        )
        self.profile = composite.ChannelProfile(
            Capabilities(composite.SIMULATOR_PROVIDER, "timed-synthetic.v1",
                         frozenset({"text", "audio"}), 6000, True),
            192000, frozenset({"text/plain", "audio/wav"}),
        )
        overlay = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile,
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)

    def approve(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return cases.record_decision(
            **self.common, answer_id=case.answers.get(revision=case.answer_revision).pk,
            action="APPROVE", expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )

    def approved(self, *, part=False):
        if part:
            self.pin = timed.inspect_source(**self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk))
        row = self.propose()
        self.confirm(row)
        self.approve()
        return row

    def release(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return media.release_private(
            **self.common, expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            manifest_sha256=AnswerManifest.objects.get(answer=case.approved_answer).sha256,
            confirmed=True,
        )

    def edition(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return publication.create_edition(
            **self.common, expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            title="عنوان تجريبي زمني", category="تصنيف تجريبي", body="نص تحريري اصطناعي",
        )

    def published(self):
        edition = self.edition()
        publication.act(**self.common, edition_id=edition["id"], action="REVIEW", reviewed=True)
        publication.act(**{**self.common, "subject_id": "publisher"},
                        edition_id=edition["id"], action="APPROVE")
        row = PublicationEdition.objects.get(pk=edition["id"])
        overlay = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=PreviewPolicy(
            (PublicationGrant(str(row.pk), row.content_sha256),), (),
            timezone.now() + timedelta(minutes=30), True,
        ))
        overlay.enable()
        self.addCleanup(overlay.disable)
        return edition

    def staged(self):
        request = composite.prepare_composite_delivery(**self.common)
        receipt = CaseDeliveryFixture.receipt(self, request, approver_id="editor")
        composite.stage_composite_delivery(**self.common, receipt=receipt,
                                          verify_receipt=self.approval_verifier)
        lease = composite.reserve_composite_part(
            **self.common, worker_id="synthetic-worker", verify_worker=lambda *_: True,
            verify_receipt=self.approval_verifier,
        )
        part = composite.resolve_composite_part(**self.common, lease=lease,
                                               verify_receipt=self.approval_verifier)
        event = self.simulator.event(lease=lease, part=part, reported="ACCEPTED")
        return lease, event

    def library(self):
        return publication.library_catalog(subject_id="editor", provider=self.directory,
                                           synthetic_fixtures_only=True)

    def test_proposed_annotation_blocks_canonical_approval(self):
        self.propose()
        with self.assertRaisesMessage(cases.CaseConflict, "timed_current_confirmation_required"):
            self.approve()
        self.assertFalse(CaseDecision.objects.exists())

    def test_confirmed_attachment_and_answer_media_allow_real_approval_and_private_bytes(self):
        self.approved(part=True)
        self.assertTrue(self.release()["available"])
        snapshot = media.requester_snapshot(token=self.receipt["token"], synthetic_fixtures_only=True)
        self.assertEqual(snapshot["package"]["text"], "PRIVATE synthetic human answer")
        raw = media.requester_read(token=self.receipt["token"], part_id=str(self.part.pk),
                                   synthetic_fixtures_only=True)["raw"]
        self.assertEqual(raw, self.audio["raw"])
        self.assertFalse(snapshot["delivery_verified"])

    def test_expiry_after_validation_rolls_back_human_approval(self):
        row = self.propose()
        self.confirm(row)
        original = media.validate_for_approval

        def expire(answer):
            result = original(answer)
            clock = patch("apps.source_rights.services.timezone.now",
                          return_value=self.rights.valid_until + timedelta(seconds=1))
            clock.start()
            self.addCleanup(clock.stop)
            return result

        with patch.object(media, "validate_for_approval", side_effect=expire):
            # Cross the exact grant deadline after parsing, before the canonical
            # transaction commits; elapsed authority must roll back the decision.
            with self.assertRaises(cases.CaseConflict):
                self.approve()
        self.assertFalse(CaseDecision.objects.exists())

    def test_approved_then_expired_blocks_private_release_files_delivery_and_publication(self):
        self.approved()
        self.release()
        edition = self.published()
        lease, event = self.staged()
        self.assertEqual(preview.browse()["total"], 1)
        self.assertEqual(self.library()["total"], 1)
        self.rights.valid_until = timezone.now() - timedelta(seconds=1)
        operations = (
            self.release,
            lambda: media.requester_snapshot(token=self.receipt["token"], synthetic_fixtures_only=True),
            lambda: media.requester_read(token=self.receipt["token"], part_id=str(self.part.pk), synthetic_fixtures_only=True),
            lambda: media.staff_read(part_id=str(self.part.pk), subject_id="editor", provider=self.directory, synthetic_fixtures_only=True),
            lambda: composite.prepare_composite_delivery(**self.common),
            lambda: composite.resolve_composite_part(**self.common, lease=lease, verify_receipt=self.approval_verifier),
            lambda: composite.record_composite_event(**self.common, lease=lease, event=event, verifier=self.simulator.verifier),
            lambda: composite.composite_status(**self.common, verifier=self.simulator.verifier),
            lambda: delivery.requester_delivery_status(self.receipt["token"], synthetic_fixtures_only=True),
            self.edition,
            lambda: knowledge.browse(publication_id=edition["id"], subject_id="editor", provider=self.directory, synthetic_fixtures_only=True),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(cases.CaseConflict):
                    operation()
        self.assertEqual(preview.browse()["total"], 0)
        self.assertEqual(preview.browse(query="زمني", category="تصنيف تجريبي", page=2)["items"], [])
        self.assertEqual(preview.browse()["categories"], [])
        self.assertEqual(self.library()["total"], 0)
        with self.assertRaises(preview.PreviewUnavailable):
            preview.read(edition["id"])
        self.assertFalse(ProviderSignatureEvidence.objects.exists())
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)
        self.assertEqual(PublicationEdition.objects.count(), 1)
        self.assertEqual(attachments._check(CaseAttachment.objects.get(pk=self.attachment["id"])), self.audio["raw"])
        self.assertEqual(media.raw_for_part(self.part), self.audio["raw"])

    def test_withdrawal_blocks_use_and_preserves_decision_and_original_pin(self):
        row = self.approved()
        self.release()
        timed.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        with self.assertRaisesMessage(cases.CaseConflict, "timed_current_confirmation_required"):
            composite.prepare_composite_delivery(**self.common)
        with self.assertRaises(cases.CaseConflict):
            media.requester_snapshot(token=self.receipt["token"], synthetic_fixtures_only=True)
        self.assertEqual(TimedCitation.objects.get(pk=row["id"]).snapshot, self.pin)
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertEqual(TimedCitationAction.objects.count(), 2)

    def test_disabled_feature_or_missing_app_cannot_hide_persisted_annotations(self):
        self.approved()
        with override_settings(FATWA_TIMED_CITATIONS_ENABLED=False):
            with self.assertRaisesMessage(cases.CaseConflict, "timed_citations_disabled"):
                self.release()
        original = cases.django_apps.is_installed
        with patch.object(cases.django_apps, "is_installed", side_effect=lambda name: False if name == "apps.timed_citations" else original(name)):
            with self.assertRaisesMessage(cases.CaseConflict, "timed_citation_schema_unavailable"):
                self.release()

    def test_new_evidence_closes_original_and_new_answer_does_not_clone_locator(self):
        row = self.approved()
        self.release()
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.add_followup(token=self.receipt["token"], text="وقائع اصطناعية جديدة",
                           expected_revision=case.revision, synthetic_fixtures_only=True)
        with self.assertRaises(cases.CaseConflict):
            media.requester_read(token=self.receipt["token"], part_id=str(self.part.pk), synthetic_fixtures_only=True)
        self.save()
        current = Case.objects.get(pk=case.pk)
        self.assertFalse(TimedCitation.objects.filter(answer__revision=current.answer_revision).exists())
        self.assertEqual(TimedCitation.objects.get(pk=row["id"]).snapshot, self.pin)

    def test_revoked_approval_identity_or_wrong_exact_source_grant_closes_use(self):
        self.approved()
        original = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(original, auth_epoch="epoch-revoked")
        with self.assertRaisesMessage(cases.CaseConflict, "timed_approval_authority_changed"):
            self.release()
        self.directory.identities["editor"] = original
        self.rights.pins = {("ATTACHMENT", str(self.part.pk), self.part.sha256)}
        with self.assertRaises(cases.CaseConflict):
            composite.prepare_composite_delivery(**self.common)

    def test_legacy_answer_without_annotations_is_unchanged_when_timed_ui_disabled(self):
        with override_settings(FATWA_TIMED_CITATIONS_ENABLED=False):
            self.approve()
            self.assertTrue(self.release()["available"])
            self.assertEqual(len(composite.prepare_composite_delivery(**self.common)["parts"]), 2)

    def test_collection_rechecks_timed_expiry_after_later_legacy_result_projection(self):
        self.approved()
        first = self.published()
        second = cases.intake_case(
            original_question="Second synthetic case", source_event_id="timed-collection-second",
            requester_id="other-synthetic", idempotency_key="timed-collection-second",
            synthetic_fixtures_only=True,
        )
        for key, actor in self.directory.identities.items():
            self.directory.identities[key] = replace(actor, case_keys=actor.case_keys | {second["public_ref"]})
        common = {**self.common, "case_id": second["case_id"]}
        draft = cases.save_answer(**common, text="Second human answer", expected_revision=1, expected_evidence_version=1)
        cases.record_decision(**common, answer_id=draft["answers"][-1]["id"], action="APPROVE",
                              expected_revision=draft["revision"], expected_evidence_version=1)
        case = Case.objects.get(pk=second["case_id"])
        other = publication.create_edition(**common, expected_revision=case.revision,
                                          expected_evidence_version=1, title="Second safe title",
                                          category="Second category", body="Second redacted body")
        publication.act(**common, edition_id=other["id"], action="REVIEW", reviewed=True)
        with override_settings(FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(second["public_ref"])):
            publication.act(**{**common, "subject_id": "publisher"}, edition_id=other["id"], action="APPROVE")
        grants = tuple(PublicationGrant(row["id"], PublicationEdition.objects.get(pk=row["id"]).content_sha256)
                       for row in (first, other))
        selected = PreviewPolicy(grants, (), timezone.now() + timedelta(minutes=30), True)
        original = preview._projection
        initial = timezone.now()
        current = [initial]

        def project(policy, edition):
            value = original(policy, edition)
            if str(edition.pk) == other["id"]:
                current[0] = self.rights.valid_until + timedelta(seconds=1)
            return value

        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=selected), patch.object(preview, "_projection", side_effect=project), patch("django.utils.timezone.now", side_effect=lambda: current[0]):
            result = preview.browse()
            self.assertEqual(result["total"], 1)
            self.assertEqual([row["id"] for row in result["items"]], [other["id"]])
            self.assertEqual(result["categories"], ["Second category"])
            self.assertNotIn(first["title"], str(result))
            self.assertEqual(preview.browse(query="زمني", category="تصنيف تجريبي", page=2)["total"], 0)
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(first["id"])

    @override_settings(ROOT_URLCONF="config.campaign_urls", MIDDLEWARE=CAMPAIGN_MIDDLEWARE)
    def test_shared_campaign_native_desk_confirmation_and_private_audio_route(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        desk = {"action": "timed_desk", "case_ref": self.receipt["public_ref"]}
        self.assertEqual(client.post("/casework/staff/", desk).status_code, 403)
        page = client.get("/casework/staff/login/")
        post(client, "/casework/staff/login/",
             {"credential": "synthetic-editor-credential-32-characters"}, page)
        page = client.get("/casework/staff/")
        page = post(client, "/casework/staff/", desk, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "100 مللي ثانية")
        case = Case.objects.get(pk=self.receipt["case_id"])
        page = post(client, "/casework/staff/", {
            "action": "timed_propose", "case_ref": self.receipt["public_ref"],
            "source_pin": signing.dumps(self.pin, salt=SALT),
            "start_ms": "10", "end_ms": "90", "reason": "Synthetic exact segment",
            "replaces_id": "", "revision": str(case.revision),
            "evidence_version": str(case.evidence_version),
        }, page)
        self.assertEqual(page.status_code, 200, page.content)
        row = TimedCitation.objects.get()
        audio_url = f"/casework/staff/timed-citations/{row.pk}/audio/"
        self.assertEqual(client.get(audio_url).status_code, 404)
        page = post(client, "/casework/staff/", {
            "action": "timed_confirm", "case_ref": self.receipt["public_ref"],
            "citation_id": str(row.pk), "confirm": "yes",
        }, page)
        self.assertEqual(page.status_code, 200, page.content)
        response = client.get(audio_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.audio["raw"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(client.get(audio_url, HTTP_X_FORWARDED_FOR="127.0.0.1").status_code, 403)
        self.assertEqual(Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(audio_url).status_code, 404)
        self.rights.actions.clear()
        self.assertEqual(client.get(audio_url).status_code, 404)
        self.assertEqual(client.head(audio_url).status_code, 404)
