"""V10 focused native desk/privacy/current-version tests; synthetic PostgreSQL only."""

import json
from dataclasses import asdict, replace
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent, ProviderReceipt
from apps.source_case_intake import services as origins
from apps.source_case_intake import simulators
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import desk, services
from . import tests as fixtures
from .simulator import OfflineProviderSimulator

SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.composite_delivery.urls",
    "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
}


class DeskFixture(CaseDeliveryFixture):
    save = fixtures.CompositeTests.save
    approve = fixtures.CompositeTests.approve
    request = fixtures.CompositeTests.request
    stage = fixtures.CompositeTests.stage
    reserve = fixtures.CompositeTests.reserve
    resolve = fixtures.CompositeTests.resolve

    def setUp(self):
        super().setUp()
        self.profile = services.ChannelProfile(
            Capabilities(
                services.SIMULATOR_PROVIDER,
                "synthetic.v10",
                frozenset({"text", "document", "audio", "image"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
        )
        self.simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        self.channel_verifier = self.simulator.verifier
        self.channels = []

        def capability(channel):
            self.channels.append(channel)
            return self.profile

        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=self.approval_verifier,
            FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=self.simulator.verifier,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=capability,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def snapshot(self, case=None):
        return desk.read_delivery_desk(**self.staff(case))

    def bundle(self, lease, part, reported):
        event = self.simulator.event(lease=lease, part=part, reported=reported)
        saved_lease = {**asdict(lease), "expires_at": lease.expires_at.isoformat()}
        return json.dumps(
            {
                "schema": desk.PROVIDER_BUNDLE_SCHEMA,
                "part_id": part["id"],
                "lease": saved_lease,
                "event": asdict(event),
            }
        )

    def login(self):
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        response = post(
            self.client,
            "/casework/staff/login/",
            {"credential": "synthetic-credential-with-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303, response.content)
        return self.client.get("/casework/staff/")

    def open(self, page, case=None):
        response = post(
            self.client,
            "/casework/staff/",
            {
                "action": "composite_open",
                "case_ref": (case or self.a)["public_ref"],
            },
            page,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        return response

    def action(self, page, action, **extra):
        values = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "plan_sha256",
            )
        }
        return post(self.client, "/casework/staff/", {**values, "action": action, **extra}, page)


@override_settings(**SETTINGS)
class DeliveryDeskTests(DeskFixture, TransactionTestCase):
    def test_multiple_origins_destination_parts_and_source_attachment_share_current_plan(self):
        cases_by_source = [self.a]
        for source in ("telegram", "youtube", "website"):
            raw = (
                simulators.telegram(document=True, thread=17)
                if source == "telegram"
                else getattr(simulators, source)()
            )
            case = origins.ingest(
                raw=raw, context=simulators.context(source), synthetic_fixtures_only=True
            )
            cases_by_source.append(case)
            if source == "telegram":
                origins.attach_fixture(
                    receipt_id=case["receipt_id"],
                    source_file_id="synthetic-file-1",
                    token=case["token"],
                    raw=b"synthetic attachment",
                    filename="synthetic.txt",
                    media_type="text/plain",
                    synthetic_fixtures_only=True,
                )
        self.directory.refs = frozenset(c["public_ref"] for c in cases_by_source)
        page = self.login()
        fingerprints = set()
        for case, channel in zip(
            cases_by_source, ("WEBSITE", "telegram", "youtube", "website"), strict=True
        ):
            self.approve(case)
            snapshot = self.snapshot(case)
            fingerprints.add(snapshot["plan_sha256"])
            self.assertEqual(snapshot["origin"]["channel"], channel)
            self.assertEqual(self.channels[-1], channel)
            self.assertEqual([p["kind"] for p in snapshot["parts"]], ["TEXT", "FILE", "AUDIO"])
            self.assertTrue(all(p["sha256"] and p["envelope_sha256"] for p in snapshot["parts"]))
            page = self.open(page, case)
            self.assertContains(page, snapshot["origin"]["identity_sha256"])
            self.assertContains(page, "إذن التجهيز المستقل")
            if channel == "telegram":
                self.assertEqual(snapshot["origin"]["conversation"], "-100123")
                self.assertEqual(snapshot["origin"]["thread"], "17")
                self.assertEqual(snapshot["evidence_version"], 2)
        self.assertEqual(len(fingerprints), 4)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_export_independent_approval_and_per_part_signed_receipt_forms(self):
        self.approve()
        page = self.open(self.login())
        exported = self.action(page, "composite_export")
        self.assertEqual(exported.status_code, 200)
        request = json.loads(exported.content)
        approval = self.receipt(request)
        page = self.action(
            page,
            "composite_stage",
            confirm="yes",
            response_json=json.dumps(
                {
                    "request_sha256": request["plan_sha256"],
                    "receipt": asdict(approval),
                }
            ),
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "إذن مستقل موقّع متحقق")
        lease = self.reserve()
        part = self.resolve(lease)
        bundle = self.bundle(lease, part, "ACCEPTED")
        page = self.open(page)
        page = self.action(
            page, "composite_receipt", part_id=part["id"], confirm="yes", response_json=bundle
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "قبول المزود فقط؛ التسليم غير مؤكد")
        self.assertNotContains(page, lease.token)
        self.assertNotContains(page, "signature_b64url")
        self.assertFalse(self.snapshot()["status"]["delivery_verified"])
        page = self.action(
            page,
            "composite_receipt",
            part_id=part["id"],
            confirm="yes",
            response_json=self.bundle(lease, part, "DELIVERED"),
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "إيصال تسليم موقّع متحقق لهذا الجزء")
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.assertContains(page, "تسليم جزئي؛ بقية الأجزاء لم يثبت تسليمها")
        self.assertEqual(self.snapshot()["status"]["verified_parts"], 1)

    def test_unknown_timeout_reconciles_then_exact_signed_part_without_retry(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        bundle = self.bundle(lease, part, "DELIVERED")
        page = self.open(self.login())
        with patch(
            "apps.delivery_queue.services.timezone.now",
            return_value=timezone.now() + timedelta(minutes=2),
        ):
            page = self.action(page, "composite_reconcile", confirm="yes")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "نتيجة غير محسومة")
        page = self.action(
            page, "composite_receipt", part_id=part["id"], confirm="yes", response_json=bundle
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.assertContains(page, "تسليم جزئي؛ بقية الأجزاء لم يثبت تسليمها")
        self.assertEqual(self.snapshot()["status"]["verified_parts"], 1)

    def test_wrong_part_case_signature_and_stale_form_never_change_provider_history(self):
        self.approve()
        self.stage()
        lease = self.reserve()
        part = self.resolve(lease)
        bundle = self.bundle(lease, part, "DELIVERED")
        page = self.open(self.login())
        second = self.snapshot()["parts"][1]
        response = self.action(
            page, "composite_receipt", part_id=second["id"], confirm="yes", response_json=bundle
        )
        self.assertEqual(response.status_code, 409)
        changed = json.loads(bundle)
        changed["event"]["signature_b64url"] = "x" * 86
        response = self.action(
            page,
            "composite_receipt",
            part_id=part["id"],
            confirm="yes",
            response_json=json.dumps(changed),
        )
        self.assertEqual(response.status_code, 409)
        self.profile = replace(self.profile, max_media_bytes=191999)
        response = self.action(
            page, "composite_receipt", part_id=part["id"], confirm="yes", response_json=bundle
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        updated = self.open(page)
        self.assertContains(updated, "تغيّرت الخطة")
        self.assertNotContains(updated, 'name="response_json"')

    def test_unapproved_new_revision_facts_or_scope_never_show_stale_parts(self):
        page = self.open(self.login())
        self.assertContains(page, "يلزم اعتماد بشري حالي")
        self.approve()
        page = self.open(page)
        approved_hash = self.snapshot()["parts"][0]["sha256"]
        self.save()
        stale = self.action(page, "composite_export")
        self.assertEqual(stale.status_code, 409)
        updated = self.open(page)
        self.assertNotContains(updated, approved_hash)
        self.approve()
        page = self.open(updated)
        current = cases.read_case(**self.staff())
        cases.add_followup(
            token=self.a["token"],
            text="وقائع اصطناعية أحدث",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        self.assertEqual(self.action(page, "composite_export").status_code, 409)
        self.directory.refs = frozenset()
        response = post(
            self.client,
            "/casework/staff/",
            {"action": "composite_open", "case_ref": self.a["public_ref"]},
            page,
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, approved_hash, status_code=403)

    def test_unsupported_media_and_ambiguous_origin_hold_all_parts_without_downgrade(self):
        self.approve()
        self.profile = replace(
            self.profile,
            capabilities=replace(self.profile.capabilities, supported=frozenset({"text"})),
        )
        page = self.open(self.login())
        self.assertContains(page, "القناة لا تقبل نوع هذا الجزء")
        self.assertEqual(sum(not p["supported"] for p in self.snapshot()["parts"]), 2)
        self.assertNotContains(page, 'name="response_json"')
        self.assertEqual(len(self.snapshot()["parts"]), 3)
        with patch.object(
            cases,
            "_delivery_origin_for_locked_case",
            side_effect=cases.CaseConflict("source_origin_unavailable"),
        ):
            page = self.open(page)
        self.assertContains(page, "ربطه غير محسوم")
        self.assertNotContains(page, 'name="plan_sha256"')
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_csrf_auth_extra_destination_fields_and_duplicate_json_fail_closed(self):
        self.approve()
        self.stage()
        page = self.open(self.login())
        self.assertEqual(
            self.client.post("/casework/staff/", {"action": "composite_open"}).status_code, 403
        )
        self.assertEqual(
            self.action(page, "composite_export", destination="other").status_code, 400
        )
        lease = self.reserve()
        part = self.resolve(lease)
        raw = self.bundle(lease, part, "DELIVERED")
        malformed = [
            raw.replace('"schema":', '"schema":"duplicate", "schema":'),
            "[NaN]",
            "[" * 2000,
        ]
        data = json.loads(raw)
        data["lease"]["token"] = 12
        malformed.append(json.dumps(data))
        for value in malformed:
            with self.subTest(value=value[:30]):
                response = self.action(
                    page,
                    "composite_receipt",
                    part_id=part["id"],
                    confirm="yes",
                    response_json=value,
                )
                self.assertEqual(response.status_code, 409)
                self.assertNotContains(response, value, status_code=409)
        self.assertEqual(ProviderReceipt.objects.count(), 0)

    def test_missing_or_revoked_independent_verifiers_do_not_claim_current_permission(self):
        self.approve()
        self.stage()
        with override_settings(
            FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER=None,
            FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=None,
        ):
            page = self.open(self.login())
            self.assertContains(page, "صلاحيته الحالية غير متحققة")
            self.assertContains(page, "التحقق من توقيع المزود غير متاح")
        self.revoked = True
        self.assertFalse(self.snapshot()["permission_valid"])

    def test_cross_case_bundle_cannot_be_relabelled_and_organizer_cannot_operate_desk(self):
        other = self.intake("other")
        self.directory.refs = frozenset({self.a["public_ref"], other["public_ref"]})
        for case in (self.a, other):
            self.approve(case)
            self.stage(case)
        first = self.reserve()
        first_part = self.resolve(first)
        foreign = self.reserve(other)
        foreign_part = self.resolve(foreign, other)
        forged_label = json.loads(self.bundle(foreign, foreign_part, "DELIVERED"))
        forged_label["part_id"] = first_part["id"]
        page = self.open(self.login())
        response = self.action(
            page,
            "composite_receipt",
            part_id=first_part["id"],
            confirm="yes",
            response_json=json.dumps(forged_label),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ProviderReceipt.objects.count(), 0)
        self.directory.role = "ORGANIZER_ADMIN"
        response = post(
            self.client,
            "/casework/staff/",
            {
                "action": "composite_open",
                "case_ref": self.a["public_ref"],
            },
            page,
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, first_part["sha256"], status_code=403)
