"""Requester-safe multipart receipts remain separate from private availability."""

from dataclasses import replace

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest
from apps.casework import services as cases
from apps.composite_delivery import services as composite
from apps.composite_delivery import tests as contracts
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryIntent
from apps.requester_access_review.services import requester_snapshot
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    }
)
class RequesterCompositeTests(CaseDeliveryFixture, TransactionTestCase):
    save = contracts.CompositeTests.save
    approve = contracts.CompositeTests.approve
    request = contracts.CompositeTests.request
    stage = contracts.CompositeTests.stage
    reserve = contracts.CompositeTests.reserve
    resolve = contracts.CompositeTests.resolve
    record = contracts.CompositeTests.record
    outcome = contracts.CompositeTests.outcome

    def setUp(self):
        super().setUp()
        self.profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav"}),
        )
        self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        self.channel_verifier = self.simulator.verifier
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile,
            FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=self.channel_verifier,
            FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED=True,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def release(self):
        current = cases.read_case(**self.staff())
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        media.release_private(
            **self.staff(),
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )

    def snapshot(self, token=None):
        return requester_snapshot(
            token or self.a["token"],
            verifier=self.channel_verifier,
            show_approved_answer=True,
            synthetic_fixtures_only=True,
        )

    def test_accepted_partial_and_complete_proof_never_unlock_legacy_text(self):
        self.approve()
        self.stage()
        self.assertIsNone(self.snapshot()["composite_delivery"])
        self.release()
        self.assertEqual(self.snapshot()["composite_delivery"]["state"], "STAGED")
        first = self.reserve()
        part = self.resolve(first)
        self.outcome(first, part, "ACCEPTED")
        snapshot = self.snapshot()
        summary = snapshot["composite_delivery"]
        self.assertEqual(summary["state"], "IN_PROGRESS")
        self.assertEqual(summary["accepted_parts"], 1)
        self.assertEqual(summary["verified_parts"], 0)
        self.assertFalse(summary["delivery_verified"])
        self.outcome(first, part, "DELIVERED")
        self.assertEqual(self.snapshot()["composite_delivery"]["state"], "PARTIALLY_DELIVERED")
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        snapshot = self.snapshot()
        summary = snapshot["composite_delivery"]
        self.assertTrue(summary["delivery_verified"])
        self.assertEqual(summary["verified_parts"], 3)
        self.assertFalse(summary["read_confirmed"])
        self.assertFalse(snapshot["case"]["delivery_verified"])
        self.assertIsNone(snapshot["private_answer"])
        self.assertEqual(
            set(summary),
            {
                "state",
                "expected_parts",
                "verified_parts",
                "accepted_parts",
                "failed_parts",
                "unresolved_parts",
                "delivery_verified",
                "read_confirmed",
                "human_action",
            },
        )
        for forbidden in (part["id"], part["sha256"], "synthetic-mufti", "source:"):
            self.assertNotIn(forbidden, str(summary))
        before = list(DeliveryIntent.objects.values())
        self.snapshot()
        self.assertEqual(before, list(DeliveryIntent.objects.values()))

    def test_context_authority_and_verifier_changes_close_summary(self):
        self.approve()
        self.stage()
        self.release()
        self.assertIsNotNone(self.snapshot()["composite_delivery"])
        self.directory.epoch = "revoked"
        self.assertIsNone(self.snapshot()["composite_delivery"])
        self.directory.epoch = "epoch-1"
        for overrides in (
            {"FATWA_COMPOSITE_DELIVERY_ENABLED": False},
            {"FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": None},
            {"FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": False},
        ):
            with override_settings(**overrides):
                self.assertIsNone(self.snapshot()["composite_delivery"])
        previous = self.profile
        self.profile = replace(self.profile, max_media_bytes=100000)
        snapshot = self.snapshot()
        self.assertTrue(snapshot["private_media_availability"]["available"])
        self.assertIsNone(snapshot["composite_delivery"])
        self.profile = previous
        current = cases.read_case(**self.staff())
        cases.add_followup(
            token=self.a["token"],
            text="changed synthetic facts",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(self.snapshot()["composite_delivery"])

    def test_other_requester_cannot_observe_plan_and_missing_stage_is_closed(self):
        other = self.intake("other")
        self.approve()
        self.release()
        self.assertIsNone(self.snapshot()["composite_delivery"])
        self.stage()
        self.assertIsNotNone(self.snapshot()["composite_delivery"])
        snapshot = self.snapshot(other["token"])
        self.assertIsNone(snapshot["composite_delivery"])
        self.assertFalse(snapshot["private_media_availability"]["available"])

    def test_http_displays_partial_failure_separately_without_legacy_false_claim(self):
        self.approve()
        self.stage()
        self.release()
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "DELIVERED")
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "FAILED")
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/status/")
        self.assertEqual(
            post(
                client,
                "/casework/status/",
                {
                    "action": "unlock",
                    "token": self.a["token"],
                },
                page,
            ).status_code,
            303,
        )
        page = client.get("/casework/status/")
        self.assertContains(page, 'id="requester-composite-delivery"')
        self.assertContains(page, "تسليم جزئي مع فشل أجزاء")
        self.assertContains(page, "مسار الإرجاع النصي القديم")
        self.assertContains(page, "محاكاة قناة تجريبية مغلقة")
        self.assertNotContains(page, "تسليم المزود غير مدعوم حاليًا")
        self.assertNotContains(page, 'id="requester-answer-text"')
        self.assertNotContains(page, 'id="composite-delivery-verified"')
        self.assertNotContains(page, self.a["token"])
        self.assertIn("no-store", page["Cache-Control"])
        summary = page.context["composite_delivery"]
        self.assertEqual(summary["failed_parts"], 1)
        self.assertTrue(summary["human_action"])
