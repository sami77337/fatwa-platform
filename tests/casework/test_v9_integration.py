"""Cross-component contracts added by the V9 integration, on isolated PostgreSQL."""

import json
import tempfile
from dataclasses import asdict
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_attachments.storage_bindings import raw_for_owner
from apps.casework import delivery as legacy_delivery
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from apps.composite_delivery import services as composite
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.private_media.filesystem import FileSystemStorage
from apps.source_case_intake import services as origins
from apps.source_case_intake import simulators
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_ANSWER_MEDIA_ENABLED=True,
    FATWA_COMPOSITE_DELIVERY_ENABLED=True,
)
class OriginStorageDeliveryTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.source = origins.ingest(
            raw=simulators.telegram(document=True),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        self.directory = TestDirectory([self.a["public_ref"], self.source["public_ref"]])
        self.root = tempfile.TemporaryDirectory(prefix="fatwa-v9-integrated-")
        self.addCleanup(self.root.cleanup)
        self.storage = FileSystemStorage(self.root.name, synthetic_fixtures_only=True)
        self.channels = []

        def profile(channel):
            self.channels.append(channel)
            return composite.ChannelProfile(
                Capabilities(
                    composite.SIMULATOR_PROVIDER,
                    "synthetic.v9",
                    frozenset({"text", "document", "audio", "image"}),
                    6000,
                    True,
                ),
                192000,
                frozenset({"text/plain", "audio/wav"}),
            )

        configured = override_settings(
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=profile,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=self.approval_verifier,
            FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=OfflineProviderSimulator(
                synthetic_fixtures_only=True
            ).verifier,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def attach(self, **changes):
        return origins.attach_fixture(
            **{
                "receipt_id": self.source["receipt_id"],
                "source_file_id": "synthetic-file-1",
                "token": self.source["token"],
                "raw": b"synthetic source original",
                "filename": "synthetic.txt",
                "media_type": "text/plain",
                "synthetic_fixtures_only": True,
                **changes,
            }
        )

    def approved(self):
        current = cases.read_case(**self.staff(self.source))
        answer = media.save_multipart_answer(
            **self.staff(self.source),
            text="جواب مركب اصطناعي للمراجعة البشرية",
            files=[audio_fixture()],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        return cases.record_decision(
            **self.staff(self.source),
            answer_id=answer["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=answer["revision"],
            expected_evidence_version=answer["evidence_version"],
        )

    def test_source_attachment_external_replay_and_authority_preserve_one_evidence(self):
        attached = self.attach()
        row = CaseAttachment.objects.get(pk=attached["id"])
        self.assertIsNone(row.original)
        self.assertEqual(row.storage_backend, "private-filesystem-v1")
        self.assertEqual(raw_for_owner(row), b"synthetic source original")
        replay = self.attach()
        self.assertFalse(replay["created"])
        self.assertEqual(replay["id"], attached["id"])
        self.assertEqual(CaseEvidence.objects.filter(case_id=self.source["case_id"]).count(), 2)
        with self.assertRaisesMessage(origins.IntakeError, "source_case_identity_mismatch"):
            self.attach(token=self.a["token"])
        with self.assertRaisesMessage(origins.IntakeError, "attachment_idempotency_conflict"):
            self.attach(raw=b"different bytes")
        self.assertEqual(CaseAttachment.objects.count(), 1)

    def test_nested_external_upload_without_preheld_binding_is_rejected(self):
        current = cases.read_case(**self.staff(self.source))
        with synthetic_queue_atomic():
            with self.assertRaisesMessage(
                cases.CaseConflict, "storage_lock_requires_outer_transaction_boundary"
            ):
                attachments.upload(
                    token=self.source["token"],
                    raw=b"synthetic nested",
                    filename="nested.txt",
                    media_type="text/plain",
                    expected_revision=current["revision"],
                    synthetic_fixtures_only=True,
                )
        self.assertEqual(CaseAttachment.objects.count(), 0)

    def test_source_attachment_mime_alias_replay_uses_canonical_validated_type(self):
        payload = audio_fixture()
        first = self.attach(**{**payload, "media_type": "audio/x-wav"})
        second = self.attach(**{**payload, "media_type": "audio/wave"})
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(second["created"])
        self.assertEqual(CaseAttachment.objects.get(pk=first["id"]).media_type, "audio/wav")

    def test_legacy_text_adapter_does_not_downgrade_external_source_to_website(self):
        CaseDeliveryFixture.approve(self, self.source)
        with self.assertRaisesMessage(cases.CaseConflict, "source_channel_requires_human_delivery"):
            legacy_delivery.prepare_case_delivery(
                **self.staff(self.source), max_chars=6000, split=False
            )
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_plan_uses_durable_actual_source_with_intake_disabled_and_fails_without_schema(self):
        self.attach()
        self.approved()
        self.assertEqual(Case.objects.get(pk=self.source["case_id"]).source.channel, "WEBSITE")
        with override_settings(FATWA_SOURCE_CASE_INTAKE_ENABLED=False):
            plan = composite.prepare_composite_delivery(**self.staff(self.source))
        self.assertEqual(plan["origin_channel"], "telegram")
        self.assertTrue(self.channels)
        self.assertEqual(set(self.channels), {"telegram"})
        installed = cases.django_apps.is_installed
        with patch.object(
            cases.django_apps,
            "is_installed",
            side_effect=lambda app: False if app == "apps.source_case_intake" else installed(app),
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "source_origin_schema_unavailable"):
                composite.prepare_composite_delivery(**self.staff(self.source))
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls"})
    def test_staff_handoff_requires_current_signed_plan_and_never_sends(self):
        self.approved()
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        result = post(
            client,
            "/casework/staff/login/",
            {
                "credential": "synthetic-credential-with-32-characters",
            },
            page,
        )
        self.assertEqual(result.status_code, 303)
        page = client.get("/casework/staff/")
        base = {"action": "composite_open", "case_ref": self.source["public_ref"]}
        page = post(client, "/casework/staff/", base, page)
        self.assertEqual(page.status_code, 200, page.content)
        prepared = composite.prepare_composite_delivery(**self.staff(self.source))
        current = cases.read_case(**self.staff(self.source))
        base.update(
            revision=str(current["revision"]),
            evidence_version=str(current["evidence_version"]),
            plan_sha256=prepared["plan_sha256"],
        )
        signed = json.dumps(
            {
                "request_sha256": prepared["plan_sha256"],
                "receipt": asdict(self.receipt(prepared)),
            }
        )
        with override_settings(FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=None):
            unavailable = post(
                client,
                "/casework/staff/",
                {
                    **base,
                    "action": "composite_stage",
                    "response_json": signed,
                    "confirm": "yes",
                },
                page,
            )
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        staged = post(
            client,
            "/casework/staff/",
            {
                **base,
                "action": "composite_stage",
                "response_json": signed,
                "confirm": "yes",
            },
            page,
        )
        self.assertEqual(staged.status_code, 200, staged.content)
        self.assertContains(staged, "لم يحدث إرسال")
        self.assertEqual(DeliveryIntent.objects.count(), 2)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        bad = post(
            client,
            "/casework/staff/",
            {
                **base,
                "action": "composite_stage",
                "response_json": signed,
                "confirm": "yes",
                "approver_role": "MUFTI",
            },
            staged,
        )
        self.assertEqual(bad.status_code, 400)
        self.attach()
        stale = post(
            client,
            "/casework/staff/",
            {
                **base,
                "action": "composite_stage",
                "response_json": signed,
                "confirm": "yes",
            },
            staged,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
