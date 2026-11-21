"""Actual due execution, current grants, immutable history and native forms."""

import io
import json
import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationAction
from apps.experimental_publication.tests_ui import fields
from tests.casework.test_http import post

from . import services
from .models import PublicationSchedule, ScheduleOutcome
from .test_support import CREDENTIAL, FEATURES, ScheduleFixture


@override_settings(**FEATURES)
class PublicationScheduleTests(ScheduleFixture, TransactionTestCase):
    def due(self, row):
        with patch(
            "django.utils.timezone.now", return_value=row["scheduled_at"] + timedelta(seconds=1)
        ):
            return services.execute_due(
                schedule_id=row["id"], provider=self.directory, synthetic_fixtures_only=True
            )

    def test_exact_future_version_waits_then_publishes_once_after_new_connection(self):
        before = (CaseEvent.objects.count(), list(AnswerRevision.objects.values_list("pk", "text")))
        row = self.schedule()
        self.assertEqual(
            services.execute_due(
                schedule_id=row["id"], provider=self.directory, synthetic_fixtures_only=True
            )["state"],
            "SCHEDULED",
        )
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        connection.close()
        result = self.due(row)
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(result["edition_id"], self.edition["id"])
        action = PublicationAction.objects.get(action="APPROVE")
        self.assertEqual(action.subject_id, "publisher")
        self.assertEqual(ScheduleOutcome.objects.get().publication_action_id, action.pk)
        self.assertEqual(self.due(row)["state"], "PUBLISHED")
        self.assertEqual(PublicationAction.objects.filter(action="APPROVE").count(), 1)
        self.assertEqual(
            before,
            (CaseEvent.objects.count(), list(AnswerRevision.objects.values_list("pk", "text"))),
        )
        self.assertEqual(
            publication.library(
                subject_id="publisher", provider=self.directory, synthetic_fixtures_only=True
            )[0]["id"],
            self.edition["id"],
        )

    def test_replay_bound_to_exact_time_target_reason_and_cancellation_is_terminal(self):
        key, at = uuid.uuid4(), timezone.now() + timedelta(minutes=5)
        row = self.schedule(request_key=key, scheduled_at=at)
        self.assertEqual(self.schedule(request_key=key, scheduled_at=at)["id"], row["id"])
        with self.assertRaises(cases.CaseConflict):
            self.schedule(request_key=key, scheduled_at=at + timedelta(seconds=1))
        services.cancel(**self.common, schedule_id=row["id"], confirmed=True)
        self.assertEqual(self.due(row)["state"], "CANCELLED")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())

    def test_newer_reviewed_edition_holds_original_without_switching_to_new_version(self):
        row = self.schedule()
        newer = self.new_edition()
        self.assertNotEqual(newer["id"], row["edition_id"])
        self.assertEqual(self.due(row)["state"], "HOLD")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        self.assertEqual(
            PublicationSchedule.objects.get().edition_id.hex, uuid.UUID(row["edition_id"]).hex
        )

    def test_new_case_facts_hold_current_schedule_and_preserve_original(self):
        row = self.schedule()
        case = Case.objects.get(pk=self.common["case_id"])
        cases.add_followup(
            token=self.receipt["token"],
            text="new synthetic material facts",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(self.due(row)["state"], "HOLD")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())

    def test_revoked_publisher_epoch_or_current_grant_never_uses_stored_permission(self):
        row = self.schedule()
        original = self.directory.identities["publisher"]
        self.directory.identities["publisher"] = replace(original, auth_epoch="revoked")
        self.assertEqual(self.due(row)["state"], "HOLD")
        self.directory.identities["publisher"] = original
        second = self.schedule()
        self.publisher.denied = True
        self.assertEqual(self.due(second)["state"], "HOLD")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())

    def test_late_authority_callback_rolls_back_approval_before_recording_hold(self):
        row = self.schedule()
        self.authority.hook = lambda values: (
            self.authority.denied.add("SCHEDULE") if values["action"] == "EXECUTE" else None
        )
        self.assertEqual(self.due(row)["state"], "HOLD")
        self.assertFalse(PublicationAction.objects.filter(action="APPROVE").exists())
        self.assertIsNone(ScheduleOutcome.objects.get().publication_action_id)

    def test_invalid_time_destination_confirmation_and_case_version_are_rejected(self):
        for changes in (
            {"scheduled_at": timezone.now()},
            {"scheduled_at": timezone.now() + timedelta(days=31)},
            {"target": "TELEGRAM"},
            {"confirmed": False},
            {"expected_revision": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.schedule(**changes)
        with (
            override_settings(FATWA_PUBLICATION_SCHEDULES_ENABLED=1),
            self.assertRaises(cases.CaseConflict),
        ):
            self.schedule()
        with (
            override_settings(FATWA_PUBLICATION_SCHEDULES_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.schedule()
        self.assertEqual(PublicationSchedule.objects.count(), 0)

    def test_sql_history_and_direct_published_forgery_are_rejected(self):
        row = self.schedule()
        for operation in (
            lambda: PublicationSchedule.objects.filter(pk=row["id"]).update(reason="changed"),
            lambda: PublicationSchedule.objects.filter(pk=row["id"]).delete(),
            lambda: services._finish(PublicationSchedule.objects.get(), "PUBLISHED", "forged"),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.due(row)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScheduleOutcome.objects.all().delete()

    def test_actual_bounded_worker_command_uses_due_time_and_is_idempotent(self):
        row = self.schedule()
        output = io.StringIO()
        with patch(
            "django.utils.timezone.now", return_value=row["scheduled_at"] + timedelta(seconds=1)
        ):
            call_command("run_due_publications", limit=1, stdout=output)
            self.assertEqual(json.loads(output.getvalue())["PUBLISHED"], 1)
            self.assertEqual(
                services.run_due(), {"PUBLISHED": 0, "HOLD": 0, "CANCELLED": 0, "SCHEDULED": 0}
            )

    def test_native_csrf_forms_bind_local_time_cancel_and_deny_forged_identity(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        self.assertEqual(
            post(client, "/casework/staff/login/", {"credential": CREDENTIAL}, page).status_code,
            303,
        )
        page = client.get("/casework/staff/")
        page = post(
            client,
            "/casework/staff/",
            {"action": "ps_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        values = fields(page, "ps_schedule")
        at = (
            (timezone.now() + timedelta(minutes=5))
            .astimezone(ZoneInfo("Asia/Amman"))
            .replace(second=0, microsecond=0)
        )
        values.update(
            edition_id=self.edition["id"],
            scheduled_at=at.strftime("%Y-%m-%dT%H:%M"),
            target=services.TARGET,
            reason="موعد اختاره الناشر",
            confirmed="yes",
        )
        self.assertEqual(
            client.post(
                "/casework/staff/", {k: v for k, v in values.items() if k != "csrfmiddlewaretoken"}
            ).status_code,
            403,
        )
        self.assertEqual(
            post(client, "/casework/staff/", {**values, "subject_id": "editor"}, page).status_code,
            400,
        )
        page = post(client, "/casework/staff/", values, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(PublicationSchedule.objects.get().scheduled_at, at)
        self.assertContains(page, "SCHEDULED")
        page = post(
            client, "/casework/staff/", {**fields(page, "ps_cancel"), "confirmed": "yes"}, page
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "CANCELLED")
        self.assertIn("no-store", page["Cache-Control"])
