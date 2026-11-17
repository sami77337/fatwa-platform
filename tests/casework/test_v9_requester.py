"""Actual per-case portal availability, distinct from signed delivery and reading."""

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerManifest
from apps.casework import services as cases
from apps.delivery_queue.models import DeliveryIntent
from apps.private_media.fixtures import synthetic_files
from apps.requester_access_review.services import requester_snapshot
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    }
)
class PortalAvailabilityTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        provider = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        provider.enable()
        self.addCleanup(provider.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/status/")
        self.assertEqual(
            post(
                self.client,
                "/casework/status/",
                {
                    "action": "unlock",
                    "token": self.a["token"],
                },
                page,
            ).status_code,
            303,
        )

    def page(self, available):
        response = self.client.get("/casework/status/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "إتاحة أجزاء الجواب في البوابة")
        if available:
            self.assertContains(response, 'value="answer_media"')
            self.assertContains(response, "متاح لك هنا بموافقة خاصة حالية")
        else:
            self.assertNotContains(response, 'value="answer_media"')
            self.assertContains(response, "لا توجد أجزاء جواب متاحة لك حاليًا")
        self.assertNotContains(response, "UNPUBLISHED SYNTHETIC ANSWER")
        return response

    def test_link_appears_only_for_current_explicit_release_and_closes_on_revocation_or_facts(self):
        self.page(False)
        name, mime, raw = next(item for item in synthetic_files() if item[1] == "application/pdf")
        draft = answers.save_multipart_answer(
            **self.staff(),
            text="UNPUBLISHED SYNTHETIC ANSWER",
            files=[{"filename": name, "media_type": mime, "raw": raw}],
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.page(False)
        approved = cases.record_decision(
            **self.staff(),
            action="APPROVE",
            answer_id=draft["answers"][-1]["id"],
            expected_revision=draft["revision"],
            expected_evidence_version=draft["evidence_version"],
        )
        self.page(False)
        manifest = AnswerManifest.objects.get(answer_id=approved["approved_answer_id"])
        answers.release_private(
            **self.staff(),
            expected_revision=approved["revision"],
            expected_evidence_version=approved["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        self.page(True)
        snapshot = requester_snapshot(
            self.a["token"],
            show_approved_answer=True,
            verifier=self.channel_verifier,
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(snapshot["private_answer"])
        self.assertFalse(snapshot["case"]["delivery_verified"])
        self.assertEqual(
            snapshot["private_media_availability"],
            {
                "available": True,
                "answer_revision": 1,
                "part_count": 2,
            },
        )
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.directory.epoch = "changed"
        self.page(False)
        self.directory.epoch = "epoch-1"
        with override_settings(FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False):
            self.page(False)
        self.page(True)
        cases.add_followup(
            token=self.a["token"],
            text="وقائع اصطناعية جديدة",
            expected_revision=approved["revision"],
            synthetic_fixtures_only=True,
        )
        self.page(False)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
