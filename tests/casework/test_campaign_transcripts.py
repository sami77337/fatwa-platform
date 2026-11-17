"""Transcript evidence must invalidate delivery authority in the shared campaign."""

from django.test import SimpleTestCase, TransactionTestCase
from django.urls import resolve

from apps.casework import delivery, services
from apps.casework.models import CaseDelivery
from apps.delivery_queue.models import ApprovalClaim
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle
from tests.casework.delivery_fixtures import CaseDeliveryFixture


class TranscriptProfileTests(SimpleTestCase):
    def test_alias_preserves_one_canonical_profile_and_dispatcher(self):
        from apps.requester_team_journey.views import staff
        from apps.transcript_case_links import settings as alias
        from config.settings import campaign_review

        self.assertEqual(alias.INSTALLED_APPS, campaign_review.INSTALLED_APPS)
        self.assertEqual(alias.ROOT_URLCONF, "config.campaign_urls")
        for root in (alias.ROOT_URLCONF, "apps.transcript_case_links.urls"):
            self.assertIs(resolve("/casework/staff/", urlconf=root).func, staff)


class TranscriptDeliveryTests(CaseDeliveryFixture, TransactionTestCase):
    def bind(self):
        preview = transcripts.preview(**self.staff(), bundle=bundle())
        return transcripts.attach(
            **self.staff(),
            upload_id=preview["upload_id"],
            external_id=preview["entries"][0].external_id,
        )

    def test_binding_rejects_previously_signed_plan_without_creating_delivery(self):
        self.approve()
        signed = self.receipt(self.request())
        self.bind()
        with self.assertRaises(services.CaseConflict):
            self.stage(receipt=signed)
        self.assertEqual(CaseDelivery.objects.count(), 0)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertFalse(self.status()["delivery_verified"])

    def test_binding_blocks_existing_lease_and_preserves_private_status(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        self.bind()
        with self.assertRaises(services.CaseConflict):
            delivery.resolve_case_delivery_text(
                **self.staff(),
                lease=lease,
                verify_receipt=self.approval_verifier,
            )
        with self.assertRaises(services.CaseConflict):
            self.reserve()
        status = self.status()
        self.assertFalse(status["delivery_verified"])
        self.assertFalse(status["read_confirmed"])
        self.assertNotIn(transcripts._entries(bundle())[0].question.text, str(status))
        self.assertNotIn(transcripts._entries(bundle())[0].answer.text, str(status))
