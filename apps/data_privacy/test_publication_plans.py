"""Destination copies and scheduled workers retain the classified publication boundary."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.experimental_publication.models import PublicationAction
from apps.publication_destinations import services as destinations
from apps.publication_destinations.models import DestinationEvent, DestinationVersion
from apps.publication_destinations.test_support import FEATURES as DESTINATION_FEATURES
from apps.publication_destinations.test_support import Fixture as DestinationFixture
from apps.publication_schedules import services as schedules
from apps.publication_schedules.models import PublicationSchedule, ScheduleOutcome
from apps.publication_schedules.test_support import FEATURES as SCHEDULE_FEATURES
from apps.publication_schedules.test_support import ScheduleFixture
from apps.source_rights.models import SourceVersion

from . import services
from .test_material_hooks import ExactGrants


@override_settings(**DESTINATION_FEATURES)
class DestinationPrivacyTests(ExactGrants, DestinationFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.saved = self.prepare(self.select())
        self.privacy_on()
        for actor in ("editor", "other", "publisher"):
            self.admit("CASE", self.receipt["case_id"], "READ", actor=actor)

    def admit_source(self):
        for actor in ("editor", "other", "publisher"):
            self.admit("PUBLICATION", self.first.pk, "READ", actor=actor)
        for actor in ("editor", "publisher"):
            self.admit("PUBLICATION", self.first.pk, "PUBLISH", actor=actor)
        self.admit("ANSWER", self.first.answer_id, "PUBLISH", actor="publisher")
        for row in SourceVersion.objects.filter(
            sourceregistration__case_id=self.receipt["case_id"]
        ):
            self.admit("SOURCE_VERSION", row.pk, "PUBLISH", actor="publisher")

    def test_private_copy_is_filtered_before_plan_history_identifiers_and_counts(self):
        result = self.read()
        for row in result["records"]:
            self.assertEqual(row["versions"], [])
            self.assertEqual(row["choices"], [])
            self.assertEqual(row["id"], "")
            self.assertEqual(row["expected_version"], 0)
        self.assertNotIn(self.first.body, repr(result))
        self.admit_source()
        visible = self.read()["records"][0]
        self.assertEqual(visible["versions"][0]["copy"]["body"], self.first.body)
        self.assertEqual(len(visible["choices"]), 1)
        self.assertNotIn(self.second.body, repr(self.read()))
        key = self.admit("PUBLICATION", self.first.pk, "READ")[0]
        del self.privacy.grants[key]
        self.assertEqual(self.read()["records"][0]["versions"], [])
        self.admit("PUBLICATION", self.first.pk, "READ")
        self.assertEqual(len(self.read()["records"][0]["versions"]), 1)

    def test_read_copy_cannot_select_a_destination_without_independent_publish(self):
        self.admit_source()
        key = self.admit("PUBLICATION", self.first.pk, "PUBLISH")[0]
        del self.privacy.grants[key]
        with self.assertRaises(services.PrivacyDenied):
            self.select(expected_version=1)
        self.assertEqual(DestinationVersion.objects.count(), 1)
        self.admit("PUBLICATION", self.first.pk, "PUBLISH")
        self.assertEqual(self.select(expected_version=1).number, 2)

    def test_current_withdrawal_keeps_only_a_receipt_after_copy_read_is_revoked(self):
        result = self.decide(self.saved, "WITHDRAW", subject="editor")
        self.assertEqual(result, {"id": str(self.saved.pk), "state": "WITHDRAW"})
        self.assertNotIn(self.first.body, repr(result))
        self.assertTrue(
            DestinationEvent.objects.filter(version=self.saved, action="WITHDRAW").exists()
        )

    def test_late_destination_callback_cannot_return_the_prepared_plan_after_privacy_revocation(
        self,
    ):
        self.admit_source()
        key = self.admit("PUBLICATION", self.first.pk, "READ")[0]
        with (
            self.assertRaises(services.PrivacyDenied),
            destinations.desk_projection(**self.common) as result,
        ):
            self.assertIn(self.first.body, repr(result))
            self.authority.hook = lambda values: self.privacy.grants.pop(key, None)
        self.authority.hook = None
        self.admit("PUBLICATION", self.first.pk, "READ")
        self.assertIn(self.first.body, repr(self.read()))


@override_settings(**SCHEDULE_FEATURES)
class SchedulePrivacyTests(ExactGrants, ScheduleFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.saved = self.schedule()
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ", actor="publisher")

    def due(self, row):
        with patch(
            "django.utils.timezone.now", return_value=row["scheduled_at"] + timedelta(seconds=1)
        ):
            return schedules.execute_due(
                schedule_id=row["id"], provider=self.directory, synthetic_fixtures_only=True
            )

    def admit_source(self):
        self.admit("PUBLICATION", self.edition["id"], "READ", "PUBLISH", actor="publisher")
        self.admit("ANSWER", self.answer_id, "PUBLISH", actor="publisher")

    def test_schedule_titles_and_history_require_copy_read_but_cancel_does_not(self):
        result = schedules.desk(**self.common)
        self.assertEqual(result["editions"], [])
        self.assertEqual(result["rows"], [])
        self.admit("PUBLICATION", self.edition["id"], "READ", actor="publisher")
        self.assertEqual(len(schedules.desk(**self.common)["rows"]), 1)
        key = self.admit("PUBLICATION", self.edition["id"], "READ", actor="publisher")[0]
        del self.privacy.grants[key]
        cancelled = schedules.cancel(**self.common, schedule_id=self.saved["id"], confirmed=True)
        self.assertEqual(cancelled["state"], "CANCELLED")
        self.assertEqual(set(cancelled), {"id", "edition_id", "state"})
        self.assertEqual(ScheduleOutcome.objects.get().action, "CANCELLED")

    def test_due_worker_rechecks_publish_and_returns_only_receipt_then_human_reschedules(self):
        self.admit("PUBLICATION", self.edition["id"], "READ", actor="publisher")
        held = self.due(self.saved)
        self.assertEqual(held["state"], "HOLD")
        self.assertEqual(set(held), {"id", "edition_id", "state"})
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        self.assertEqual(ScheduleOutcome.objects.get().action, "HOLD")
        self.admit_source()
        next_schedule = self.schedule()
        self.assertEqual(PublicationSchedule.objects.count(), 2)
        self.assertEqual(self.due(next_schedule)["state"], "PUBLISHED")
        self.assertEqual(PublicationAction.objects.filter(action="APPROVE").count(), 1)
        self.assertEqual(self.due(self.saved)["state"], "HOLD")

    def test_late_schedule_authority_revocation_rolls_back_approval_and_retains_hold(self):
        self.admit_source()
        key = self.admit("PUBLICATION", self.edition["id"], "PUBLISH", actor="publisher")[0]

        def late(values):
            if values["action"] == "EXECUTE":
                self.privacy.grants.pop(key, None)

        self.authority.hook = late
        self.assertEqual(self.due(self.saved)["state"], "HOLD")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        self.assertEqual(ScheduleOutcome.objects.get().action, "HOLD")
        self.assertEqual(PublicationSchedule.objects.count(), 1)
