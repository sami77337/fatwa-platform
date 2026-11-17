"""Legacy tracking cannot override or misreport a canonical operational case."""
from datetime import timedelta

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services
from apps.casework.models import Case
from apps.delivery_queue import requester_tracking as legacy


class TrackingBridgeTests(TransactionTestCase):
    def setUp(self):
        self.created = services.intake_case(
            original_question="سؤال اصطناعي لاختبار مصدر الحالة الواحد",
            source_event_id="bridge-source",
            requester_id="bridge-requester",
            idempotency_key="bridge-idempotency",
            synthetic_fixtures_only=True,
        )
        self.case = Case.objects.get(pk=self.created["case_id"])

    def test_legacy_read_cannot_report_independent_stage(self):
        result = services.add_followup(
            token=self.created["token"], text="توضيح اصطناعي جديد",
            expected_revision=1, synthetic_fixtures_only=True,
        )
        self.assertEqual(result["status"], "UNDER_REVIEW")
        self.assertEqual(self.case.tracking.stage, "RECEIVED")
        with self.assertRaisesRegex(legacy.TrackingDenied, "canonical_case_service_required"):
            legacy.lookup_case_status(self.created["token"])
        self.assertEqual(services.requester_status(
            self.created["token"], synthetic_fixtures_only=True,
        )["status"], "UNDER_REVIEW")

    def test_legacy_mutations_cannot_change_bound_tracking_or_tokens(self):
        for operation in (
            lambda: legacy.advance_tracking_case(
                case_key=self.case.tracking_id, expected_revision=1, stage="UNDER_REVIEW",
                actor_id="legacy-operator", authorize_actor=lambda *_: True,
            ),
            lambda: legacy.rotate_tracking_token(
                case_key=self.case.tracking_id, operator_id="legacy-operator",
                authorize_operator=lambda *_: True, expires_at=timezone.now() + timedelta(days=1),
            ),
        ):
            with self.assertRaisesRegex(legacy.TrackingDenied, "canonical_case_service_required"):
                operation()
        self.assertEqual(services.requester_status(
            self.created["token"], synthetic_fixtures_only=True,
        )["revision"], 1)

    def test_reserved_identity_cannot_be_provisioned_without_operational_case(self):
        with self.assertRaisesRegex(legacy.TrackingDenied, "canonical_case_service_required"):
            legacy.provision_tracking_case(
                case_key="case:unbound", operator_id="legacy-operator",
                authorize_operator=lambda *_: True, expires_at=timezone.now() + timedelta(days=1),
            )

    def test_legacy_profile_without_casework_app_still_denies_bound_token(self):
        from django.conf import settings

        installed = [app for app in settings.INSTALLED_APPS if not app.startswith("apps.casework")]
        with override_settings(INSTALLED_APPS=installed):
            with self.assertRaisesRegex(legacy.TrackingDenied, "canonical_case_service_required"):
                legacy.lookup_case_status(self.created["token"])

    def test_existing_standalone_tracking_still_works(self):
        token = legacy.provision_tracking_case(
            case_key="standalone-fixture", operator_id="legacy-operator",
            authorize_operator=lambda *_: True, expires_at=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(legacy.lookup_case_status(token)["status"], "RECEIVED")
