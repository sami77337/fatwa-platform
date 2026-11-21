"""Explicit text-only selection never silently omits media or reuses a signature."""

import json
from dataclasses import replace
from unittest.mock import patch

from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent
from apps.experimental_publication.tests_ui import fields
from tests.casework.test_http import post

from . import desk, services, views
from .models import CompositeDelivery
from .test_desk import SETTINGS, DeskFixture

FEATURES = {
    **SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_COMPOSITE_CHOICES_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


class SelectionFixture(DeskFixture):
    def setUp(self):
        super().setUp()
        self.directory.projection_epoch = lambda: repr(
            (
                self.directory.provider_id,
                self.directory.refs,
                self.directory.role,
                self.directory.epoch,
            )
        )
        self.approve()

    def chosen(self):
        return services.prepare_composite_delivery(**self.staff(), selection_mode="TEXT_ONLY")

    def stage_chosen(self, receipt=None):
        return services.stage_composite_delivery(
            **self.staff(),
            selection_mode="TEXT_ONLY",
            receipt=receipt or self.receipt(self.chosen()),
            verify_receipt=self.approval_verifier,
        )


@override_settings(**FEATURES)
class ExplicitSelectionTests(SelectionFixture, TransactionTestCase):
    def test_configured_identity_and_pure_epoch_are_required_before_returning_a_selected_plan(self):
        from tests.casework.test_core import TestDirectory

        impostor = TestDirectory(self.directory.refs)
        impostor.projection_epoch = self.directory.projection_epoch
        with self.assertRaises(cases.CaseConflict):
            services.prepare_composite_delivery(
                **self.staff(provider=impostor), selection_mode="TEXT_ONLY"
            )
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.chosen()

        def changing_capability(_channel):
            self.directory.epoch = "epoch-changed-during-selection"
            return self.profile

        with (
            override_settings(FATWA_COMPOSITE_DELIVERY_CAPABILITIES=changing_capability),
            self.assertRaises(cases.CaseConflict),
        ):
            self.chosen()
        self.assertEqual(CompositeDelivery.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_exact_text_choice_preserves_approved_audio_and_full_manifest_but_only_delivers_text(
        self,
    ):
        before = (
            CaseEvent.objects.count(),
            list(AnswerRevision.objects.values()),
            list(AnswerPart.objects.order_by("pk").values()),
        )
        full, selected = self.request(), self.chosen()
        self.assertEqual(selected["manifest_sha256"], full["manifest_sha256"])
        self.assertEqual(selected["selection_mode"], "TEXT_ONLY")
        self.assertEqual([p["kind"] for p in selected["parts"]], ["TEXT"])
        self.assertEqual([p["kind"] for p in selected["omitted_parts"]], ["FILE", "AUDIO"])
        self.assertNotEqual(selected["plan_sha256"], full["plan_sha256"])
        receipt = self.receipt(selected)
        self.stage_chosen(receipt)
        connection.close()
        self.stage_chosen(receipt)
        self.assertEqual(DeliveryIntent.objects.count(), 1)
        lease = self.reserve()
        part = self.resolve(lease)
        self.assertEqual(part["raw"], AnswerRevision.objects.get().text.encode())
        services.record_composite_event(
            **self.staff(),
            lease=lease,
            event=self.simulator.event(lease=lease, part=part, reported="DELIVERED"),
            verifier=self.channel_verifier,
        )
        self.assertIsNone(self.reserve())
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        status = services.composite_status(**self.staff(), verifier=self.channel_verifier)
        self.assertTrue(status["delivery_verified"])
        self.assertEqual(status["expected_parts"], 1)
        self.assertEqual(AnswerManifest.objects.get().part_count, 3)
        self.assertEqual(
            before,
            (
                CaseEvent.objects.count(),
                list(AnswerRevision.objects.values()),
                list(AnswerPart.objects.order_by("pk").values()),
            ),
        )
        self.assertEqual(desk.read_delivery_desk(**self.staff())["selection_mode"], "TEXT_ONLY")

    def test_unsupported_audio_never_selects_text_implicitly_and_all_part_signature_cannot_authorize_subset(
        self,
    ):
        full = self.request()
        with self.assertRaises(ValueError):
            self.stage_chosen(self.receipt(full))
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.profile = replace(
            self.profile,
            capabilities=replace(self.profile.capabilities, supported=frozenset({"text"})),
        )
        self.assertEqual(self.request()["plan"]["status"], "REQUIRES_HUMAN_DECISION")
        selected = self.chosen()
        self.assertEqual(selected["plan"]["status"], "PLANNED_NOT_SENT")
        self.assertEqual(len(selected["omitted_parts"]), 2)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_binding_cannot_switch_selection_or_erase_history_and_revocation_denies_new_lease(self):
        self.stage_chosen()
        with self.assertRaises(cases.CaseConflict):
            services.prepare_composite_delivery(**self.staff(), selection_mode="ALL")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CompositeDelivery.objects.all().update(selection_mode="ALL")
        with (
            override_settings(FATWA_COMPOSITE_CHOICES_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.reserve()
        self.directory.refs = frozenset()
        with self.assertRaises(cases.CaseConflict):
            self.reserve()
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_schema_downgrade_cannot_erase_a_recorded_text_only_choice(self):
        self.stage_chosen()
        try:
            with self.assertRaises(DatabaseError):
                call_command("migrate", "composite_delivery", "0002", verbosity=0)
        finally:
            # Later migrations can reverse before the populated-choice guard
            # rejects its own reversal. Restore their exact schema for readers.
            call_command("migrate", "composite_delivery", verbosity=0)
        self.assertEqual(CompositeDelivery.objects.get().selection_mode, "TEXT_ONLY")
        self.assertEqual(DeliveryIntent.objects.count(), 1)
        self.assertIsNotNone(self.reserve())

    def test_native_choice_export_and_signed_stage_expose_omissions(self):
        page = self.open(self.login())
        self.assertContains(page, "معاينة خطة النص فقط")
        page = post(
            self.client,
            "/casework/staff/",
            {**fields(page, "composite_choice"), "confirm": "yes"},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'data-selection="TEXT_ONLY"')
        self.assertContains(page, 'id="omitted-parts"')
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        response = post(self.client, "/casework/staff/", fields(page, "composite_export"), page)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["selection_mode"], "TEXT_ONLY")
        from dataclasses import asdict

        receipt = self.receipt(data)
        encoded = asdict(receipt)
        bundle = json.dumps({"request_sha256": data["plan_sha256"], "receipt": encoded})
        page = post(
            self.client,
            "/casework/staff/",
            {**fields(page, "composite_stage"), "confirm": "yes", "response_json": bundle},
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'data-selection="TEXT_ONLY"')
        self.assertEqual(CompositeDelivery.objects.get().selection_mode, "TEXT_ONLY")
        self.assertEqual(DeliveryIntent.objects.count(), 1)

    def test_render_time_scope_revocation_discards_choice_response(self):
        page = self.open(self.login())
        native_render = views.render

        def revoked(*args, **kwargs):
            response = native_render(*args, **kwargs)
            if kwargs.get("status", 200) == 200:
                self.directory.refs = frozenset()
            return response

        with patch.object(views, "render", side_effect=revoked):
            response = post(
                self.client,
                "/casework/staff/",
                {**fields(page, "composite_choice"), "confirm": "yes"},
                page,
            )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotContains(response, 'id="omitted-parts"', status_code=409)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
