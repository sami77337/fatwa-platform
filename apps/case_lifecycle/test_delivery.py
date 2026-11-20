"""Closure never turns pending, failed or unsigned transport into success."""

import uuid

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.models import DeliveryIntent
from apps.requester_portal.test_support import PortalFixture
from tests.casework.delivery_fixtures import CaseDeliveryFixture

from . import services
from .models import LifecycleEvent
from .tests import Authority


@override_settings(FATWA_CASE_LIFECYCLE_ENABLED=True)
class DeliveryClosureTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.authority = Authority([self.a["public_ref"]], self.directory.provider_id)
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_CASE_LIFECYCLE_AUTHORITY=self.authority,
            FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=self.channel_verifier,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.approve()

    def close(self, **changes):
        case = Case.objects.get(pk=self.a["case_id"])
        return services.command(
            **self.staff(),
            action="CLOSE",
            reason="أغلق بعد التحقق من التوصيل",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_version=0,
            command_id=uuid.uuid4(),
            **changes,
        )

    def test_staged_and_accepted_are_not_closeable_even_with_no_delivery_override(self):
        self.stage()
        for without in (False, True):
            with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
                self.close(without_delivery=without)
        lease = self.reserve()
        self.record(lease, self.event(lease, reported="ACCEPTED"))
        with self.assertRaises(cases.CaseConflict):
            self.close()
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_signed_partial_failure_does_not_close_or_disappear(self):
        self.stage()
        first = self.reserve()
        self.record(first)
        second = self.reserve()
        self.record(second, self.event(second, reported="FAILED"))
        with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
            self.close()
        self.assertEqual(DeliveryIntent.objects.filter(state="FAILED_REQUIRES_REVIEW").count(), 1)
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_complete_signed_delivery_closes_without_changing_any_transport_state(self):
        self.stage()
        self.deliver()
        before = list(DeliveryIntent.objects.values())
        result = self.close()
        self.assertEqual(result["state"], "CLOSED")
        self.assertEqual(LifecycleEvent.objects.get().context["delivery"], "SIGNED_COMPLETE")
        self.assertFalse(LifecycleEvent.objects.get().context["read_confirmed"])
        self.assertEqual(before, list(DeliveryIntent.objects.values()))

    def test_verified_local_state_without_current_verifier_cannot_close(self):
        self.stage()
        self.deliver()
        with override_settings(FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=None):
            with self.assertRaisesMessage(cases.CaseConflict, "delivery_unresolved"):
                self.close()


@override_settings(
    FATWA_CASE_LIFECYCLE_ENABLED=True,
    FATWA_COMPOSITE_DELIVERY_ENABLED=True,
    FATWA_ANSWER_MEDIA_ENABLED=True,
)
class CompositeClosureTests(PortalFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.authority = Authority([self.a["public_ref"]], self.directory.provider_id)
        configured = override_settings(
            FATWA_CASE_LIFECYCLE_AUTHORITY=self.authority,
            FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=None,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.approve()

    close = DeliveryClosureTests.close

    def test_multipart_uses_its_own_verifier_and_requires_every_current_part(self):
        self.stage()
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "DELIVERED")
        with self.assertRaises(cases.CaseConflict):
            self.close()
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        self.assertEqual(self.close()["state"], "CLOSED")
        self.assertEqual(LifecycleEvent.objects.get().context["plans"][0]["parts"], 3)

    def test_missing_composite_verifier_is_not_replaced_by_unrelated_legacy_verifier(self):
        self.stage()
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        with override_settings(FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=None):
            with self.assertRaises(cases.CaseConflict):
                self.close()
