"""The legacy and composite signed-return plans retain exact answer privacy."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.casework import delivery
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseSource
from apps.composite_delivery import services as composite
from apps.composite_delivery import tests as composite_tests
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import ApprovalClaim, DeliveryAuditEvent, DeliveryIntent
from tests.casework.delivery_fixtures import CaseDeliveryFixture

from . import services
from .catalog import locate
from .test_support import Authority, PrivacyFixture


class DeliveryPrivacyAssertions:
    principal = PrivacyFixture.principal
    allow = PrivacyFixture.allow
    classify = PrivacyFixture.classify

    def setUp(self):
        super().setUp()
        self.configure_transport()
        self.approve()
        self.answer = AnswerRevision.objects.get(case_id=self.a["case_id"])
        self.directory.current = self.directory.resolve("synthetic-mufti")
        self.directory.resolve = lambda subject: (
            self.directory.current if subject == "synthetic-mufti" else None
        )
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.authority = Authority()
        self.enterContext(
            override_settings(
                FATWA_DATA_PRIVACY_ENABLED=True,
                FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
                FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            )
        )
        self.target = locate("CASE", self.a["case_id"])
        self.classify()
        self.allow(self.target, "CONFIDENTIAL", "READ")
        self.answer_target = locate("ANSWER", self.answer.pk)
        self.before = self.originals()

    def configure_transport(self):
        pass

    def originals(self):
        return {
            model._meta.db_table: list(model.objects.order_by("pk").values())
            for model in (Case, CaseSource, CaseEvent, AnswerRevision, CaseDecision)
        }

    def admit_answer(self):
        if not services.history(self.answer_target):
            self.classify(self.answer_target)
        key = self.allow(self.answer_target, "CONFIDENTIAL", "READ")
        if hasattr(self.answer, "media_manifest"):
            for part in self.answer.media_manifest.parts.all():
                target = locate("ANSWER_PART", part.pk)
                if not services.history(target):
                    self.classify(target)
                self.allow(target, "CONFIDENTIAL", "READ")
        return key

    def test_case_envelope_does_not_grant_unclassified_answer_plan(self):
        with self.assertRaises(services.PrivacyDenied):
            self.request()
        self.admit_answer()
        self.assertEqual(self.request()["status"], "REQUEST_NOT_APPROVED")
        self.assertEqual(self.originals(), self.before)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_publish_grant_is_not_borrowed_by_private_signed_return(self):
        self.classify(self.answer_target)
        self.allow(self.answer_target, "CONFIDENTIAL", "PUBLISH")
        with self.assertRaises(services.PrivacyDenied):
            self.request()
        self.admit_answer()
        self.assertEqual(self.request()["status"], "REQUEST_NOT_APPROVED")
        self.assertEqual(self.originals(), self.before)

    def test_late_revocation_rolls_back_the_actual_staged_signed_plan(self):
        key = self.admit_answer()
        receipt = self.receipt(self.request())
        original = delivery.adapter.commit_signed_approved_plan

        def commit_then_revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertGreater(DeliveryIntent.objects.count(), 0)
            del self.authority.grants[key]
            return result

        with (
            patch.object(
                delivery.adapter, "commit_signed_approved_plan", side_effect=commit_then_revoke
            ),
            self.assertRaises(services.PrivacyDenied),
        ):
            self.stage(receipt=receipt)
        for model in (ApprovalClaim, DeliveryIntent, DeliveryAuditEvent):
            self.assertEqual(model.objects.count(), 0)
        self.admit_answer()
        self.assertEqual(self.stage(receipt=receipt)["status"], "STAGED_NOT_SENT")
        self.assertEqual(self.originals(), self.before)

    def test_reserved_answer_cannot_be_resolved_after_current_read_revocation(self):
        key = self.admit_answer()
        self.stage()
        lease = self.reserve()
        first = self.resolve(lease)
        del self.authority.grants[key]
        with self.assertRaises(services.PrivacyDenied):
            self.resolve(lease)
        self.admit_answer()
        self.assertEqual(self.resolve(lease), first)
        self.assertEqual(self.originals(), self.before)


class DeliveryClassificationTests(
    DeliveryPrivacyAssertions, CaseDeliveryFixture, TransactionTestCase
):
    def resolve(self, lease):
        return delivery.resolve_case_delivery_text(
            **self.staff(), lease=lease, verify_receipt=self.approval_verifier
        )


@override_settings(FATWA_COMPOSITE_DELIVERY_ENABLED=True, FATWA_ANSWER_MEDIA_ENABLED=True)
class CompositeDeliveryClassificationTests(
    DeliveryPrivacyAssertions, CaseDeliveryFixture, TransactionTestCase
):
    save = composite_tests.CompositeTests.save
    approve = composite_tests.CompositeTests.approve
    request = composite_tests.CompositeTests.request
    stage = composite_tests.CompositeTests.stage
    reserve = composite_tests.CompositeTests.reserve
    resolve = composite_tests.CompositeTests.resolve

    def configure_transport(self):
        profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )
        self.enterContext(
            override_settings(FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: profile)
        )
