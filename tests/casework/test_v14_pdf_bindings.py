"""Canonical PDF locator vetoes: actual services, private bytes and PostgreSQL."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core import signing
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart, PrivateAnswerRelease
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
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority
from apps.knowledge_links import services as knowledge
from apps.library_preview import services as preview
from apps.pdf_citations import integration as pdf_integration
from apps.pdf_citations import services as pdf
from apps.pdf_citations.models import PdfCitation, PdfCitationAction
from apps.pdf_citations.tests import SETTINGS, Fixture
from apps.pdf_citations.views import SALT
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import MaintenanceUnavailable, mutation_scope
from apps.private_media.filesystem import FileSystemStorage
from apps.source_rights.tests import Authority as RightsAuthority
from config.settings.campaign_review import MIDDLEWARE as CAMPAIGN_MIDDLEWARE
from tests.casework import test_v13_timed_bindings as timed_fixture
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
    "FATWA_RECOVERY_MAINTENANCE_REQUIRED": False,
}


@override_settings(**FEATURES)
class PdfBindingsTests(Fixture, TransactionTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="v14-pdf-boundary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        storage_config = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        storage_config.enable()
        self.addCleanup(storage_config.disable)
        super().setUp()
        self.rights.valid_until = timezone.now() + timedelta(minutes=10)
        self.now = timezone.now()
        self.approval_key = Ed25519PrivateKey.generate()
        self.approval_verifier = Ed25519ApprovalVerifier(
            issuer="synthetic-mufti",
            audience="synthetic-case-return",
            trusted_public_keys={"mufti-key": self.approval_key.public_key().public_bytes_raw()},
            identity_lookup=lambda subject: IdentityStatus(subject, "MUFTI", True),
            is_revoked_or_consumed=lambda *_: False,
            clock=lambda: self.now,
        )
        self.profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "pdf-synthetic.v1",
                frozenset({"text", "document"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "application/pdf"}),
        )
        self.control = self.root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(
            root=self.control, storage=self.storage, synthetic_fixtures_only=True
        )
        config = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile,
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=self.control,
        )
        config.enable()
        self.addCleanup(config.disable)
        with mutation_scope():
            self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)

    approve = timed_fixture.TimedBindingsTests.approve
    release = timed_fixture.TimedBindingsTests.release
    edition = timed_fixture.TimedBindingsTests.edition
    published = timed_fixture.TimedBindingsTests.published
    library = timed_fixture.TimedBindingsTests.library
    # Reuse the unchanged two-result expiry adversary with this class's PDF
    # fixture/approval. This checks collection totals/categories, not just bytes.
    test_collection_rechecks_pdf_expiry_after_later_unannotated_projection = timed_fixture.TimedBindingsTests.test_collection_rechecks_timed_expiry_after_later_legacy_result_projection

    def staged(self):
        # The independent local provider fixture participates in maintenance too.
        with mutation_scope():
            return timed_fixture.TimedBindingsTests.staged(self)

    def approved(self, *, part=False):
        if part:
            self.pin = pdf.inspect_source(
                **self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk)
            )
        row = self.propose(printed_label="ورقة اصطناعية ب", printed_confirmed=True)
        self.confirm(row)
        self.approve()
        return row

    def private_read(self):
        return media.requester_read(
            token=self.receipt["token"], part_id=str(self.part.pk), synthetic_fixtures_only=True
        )

    def test_pending_pdf_locator_blocks_scholarly_approval_without_a_decision(self):
        self.propose()
        with self.assertRaisesMessage(cases.CaseConflict, "pdf_current_confirmation_required"):
            self.approve()
        self.assertFalse(CaseDecision.objects.exists())

    def test_confirmed_attachment_and_answer_part_allow_private_exact_original(self):
        for use_part in (False, True):
            with self.subTest(answer_part=use_part):
                if use_part:
                    # A new answer requires a new explicit locator; no automatic migration.
                    self.save()
                    current = Case.objects.get(pk=self.receipt["case_id"])
                    self.part = AnswerPart.objects.get(
                        manifest__answer__revision=current.answer_revision, kind="FILE"
                    )
                    self.rights.pins.add(("ANSWER_MEDIA", str(self.part.pk), self.part.sha256))
                self.approved(part=use_part)
                self.assertTrue(self.release()["available"])
                self.assertEqual(self.private_read()["raw"], self.pdf["raw"])
                snapshot = media.requester_snapshot(
                    token=self.receipt["token"], synthetic_fixtures_only=True
                )
                self.assertFalse(snapshot["delivery_verified"])
                self.assertEqual(snapshot["package"]["text"], "PRIVATE human answer")

    def test_expiry_after_media_validation_rolls_back_scholarly_approval(self):
        row = self.propose()
        self.confirm(row)
        original = media.validate_for_approval

        def expire(answer):
            result = original(answer)
            clock = patch(
                "django.utils.timezone.now",
                return_value=self.rights.valid_until + timedelta(seconds=1),
            )
            clock.start()
            self.addCleanup(clock.stop)
            return result

        with (
            patch.object(media, "validate_for_approval", side_effect=expire),
            self.assertRaises(cases.CaseConflict),
        ):
            self.approve()
        self.assertFalse(CaseDecision.objects.exists())

    def test_each_read_and_cite_revocation_closes_all_downstream_surfaces(self):
        self.approved()
        self.release()
        edition = self.published()
        lease, event = self.staged()
        self.assertEqual(preview.browse()["total"], 1)
        self.assertEqual(self.library()["total"], 1)
        operations = (
            self.release,
            self.private_read,
            lambda: media.requester_snapshot(
                token=self.receipt["token"], synthetic_fixtures_only=True
            ),
            lambda: media.staff_read(
                part_id=str(self.part.pk),
                subject_id="editor",
                provider=self.directory,
                synthetic_fixtures_only=True,
            ),
            lambda: composite.prepare_composite_delivery(**self.common),
            lambda: composite.resolve_composite_part(
                **self.common, lease=lease, verify_receipt=self.approval_verifier
            ),
            lambda: composite.record_composite_event(
                **self.common, lease=lease, event=event, verifier=self.simulator.verifier
            ),
            lambda: delivery.requester_delivery_status(
                self.receipt["token"], synthetic_fixtures_only=True
            ),
            self.edition,
            lambda: knowledge.browse(
                publication_id=edition["id"],
                subject_id="editor",
                provider=self.directory,
                synthetic_fixtures_only=True,
            ),
        )
        for action in ("READ_MEDIA", "CITE"):
            self.rights.actions = {"READ_MEDIA", "CITE"} - {action}
            for operation in operations:
                with (
                    self.subTest(action=action, operation=operation),
                    self.assertRaises(cases.CaseConflict),
                ):
                    operation()
            for filters in ({}, {"query": "زمني", "category": "تصنيف تجريبي", "page": 2}):
                result = preview.browse(**filters)
                self.assertEqual(
                    (result["total"], result["items"], result["categories"]), (0, [], [])
                )
            self.assertEqual(self.library()["total"], 0)
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(edition["id"])
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)
        self.assertEqual(PublicationEdition.objects.count(), 1)
        self.assertFalse(ProviderSignatureEvidence.objects.exists())
        self.assertEqual(media.raw_for_part(self.part), self.pdf["raw"])
        self.assertEqual(
            attachments._check(CaseAttachment.objects.get(pk=self.attachment["id"])),
            self.pdf["raw"],
        )

    def test_expired_pdf_grant_blocks_existing_release_and_publication(self):
        self.approved()
        self.release()
        edition = self.published()
        self.rights.valid_until = timezone.now() - timedelta(seconds=1)
        for operation in (self.release, self.private_read, self.edition):
            with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(preview.browse()["total"], 0)
        with self.assertRaises(preview.PreviewUnavailable):
            preview.read(edition["id"])

    def test_withdrawal_retains_history_but_closes_approved_answer_use(self):
        row = self.approved()
        self.release()
        pdf.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        for operation in (self.release, self.private_read, self.edition):
            with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(PdfCitation.objects.get(pk=row["id"]).snapshot, self.pin)
        self.assertEqual(PdfCitationAction.objects.count(), 2)
        self.assertEqual(CaseDecision.objects.count(), 1)

    def test_disabled_feature_or_omitted_app_cannot_hide_persisted_pdf(self):
        self.approved()
        with (
            override_settings(FATWA_PDF_CITATIONS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.release()
        original = pdf_integration.apps.is_installed
        with patch.object(
            pdf_integration.apps,
            "is_installed",
            side_effect=lambda name: False if name == "apps.pdf_citations" else original(name),
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "pdf_citation_schema_unavailable"):
                self.release()

    def test_evidence_change_closes_original_and_new_answer_does_not_copy_locator(self):
        row = self.approved()
        self.release()
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع اصطناعية جديدة",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.private_read()
        self.save()
        current = Case.objects.get(pk=case.pk)
        self.assertFalse(
            PdfCitation.objects.filter(answer__revision=current.answer_revision).exists()
        )
        self.assertEqual(PdfCitation.objects.get(pk=row["id"]).snapshot, self.pin)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)

    def test_frozen_control_rejects_pdf_mutations_and_canonical_approval(self):
        row = self.propose()
        before = (
            PdfCitation.objects.count(),
            PdfCitationAction.objects.count(),
            CaseDecision.objects.count(),
        )
        self.assertEqual(
            maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"], "FROZEN"
        )
        for operation in (self.propose, lambda: self.confirm(row), self.approve):
            with self.subTest(operation=operation), self.assertRaises(MaintenanceUnavailable):
                operation()
        self.assertEqual(
            before,
            (
                PdfCitation.objects.count(),
                PdfCitationAction.objects.count(),
                CaseDecision.objects.count(),
            ),
        )

    @override_settings(ROOT_URLCONF="config.campaign_urls", MIDDLEWARE=CAMPAIGN_MIDDLEWARE)
    def test_shared_dispatcher_exact_private_pdf_routes_and_current_rights(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        desk = {"action": "pdf_desk", "case_ref": self.receipt["public_ref"]}
        self.assertEqual(client.post("/casework/staff/", desk).status_code, 403)
        page = client.get("/casework/staff/login/")
        self.assertEqual(
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                page,
            ).status_code,
            303,
        )
        page = client.get("/casework/staff/")
        page = post(client, "/casework/staff/", desk, page)
        self.assertEqual(page.status_code, 200, page.content)
        case = Case.objects.get(pk=self.receipt["case_id"])
        page = post(
            client,
            "/casework/staff/",
            {
                "action": "pdf_propose",
                "case_ref": self.receipt["public_ref"],
                "source_pin": signing.dumps(self.pin, salt=SALT),
                "page_number": "2",
                "printed_label": "7",
                "printed_confirmed": "yes",
                "reason": "Human mapped synthetic page",
                "replaces_id": "",
                "revision": str(case.revision),
                "evidence_version": str(case.evidence_version),
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        row = PdfCitation.objects.get()
        url = f"/casework/staff/pdf-citations/{row.pk}/document/"
        self.assertEqual(client.get(url).status_code, 404)
        page = post(
            client,
            "/casework/staff/",
            {
                "action": "pdf_confirm",
                "case_ref": self.receipt["public_ref"],
                "citation_id": str(row.pk),
                "confirm": "yes",
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.pdf["raw"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(client.head(url).status_code, 200)
        # The shared CaseworkGuard rejects all query-bearing private-file URLs
        # as malformed, before the standalone app's method guard is reached.
        self.assertEqual(client.get(url + "?page=2").status_code, 400)
        self.assertEqual(client.get(url, HTTP_X_FORWARDED_FOR="127.0.0.1").status_code, 403)
        self.assertEqual(
            Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(url).status_code, 404
        )
        self.rights.actions.discard("CITE")
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.head(url).status_code, 404)
