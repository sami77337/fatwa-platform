"""Focused owned PostgreSQL/HTTP checks; no real message or automatic fatwa approval."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import connections
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media_services
from apps.answer_media import tests as answer_tests
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.casework.models import CaseDecision
from apps.casework_web import access
from apps.composite_delivery import services as composite
from apps.composite_delivery.models import CompositeDelivery
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent, ProviderSignatureEvidence
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services
from .fixtures import FixtureOperatorAuthority, setup_synthetic_fixture


class Operator(FixtureOperatorAuthority):
    def __init__(self, provider_id, actor, case_ref):
        self.allowed = True
        self.provider_id, self.subject_id, self.epoch, self.case_ref = (
            provider_id,
            actor.subject_id,
            actor.auth_epoch,
            case_ref,
        )
        self.actions = {"OPEN", "AUTHORIZE_RETURN", "REPORT_PROVIDER"}

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            self.allowed
            and action in self.actions
            and (provider_id, subject_id, auth_epoch, case_ref)
            == (self.provider_id, self.subject_id, self.epoch, self.case_ref)
        )


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "apps.pilot_workbench.urls",
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
        "FATWA_COMPOSITE_DELIVERY_ENABLED": True,
    }
)
class PilotTests(TransactionTestCase):
    save = answer_tests.AnswerMediaTests.save
    approve = answer_tests.AnswerMediaTests.approve

    def setUp(self):
        answer_tests.AnswerMediaTests.setUp(self)
        self.profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic-pilot.v1",
                frozenset({"text", "audio", "document"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain", "audio/wav"}),
        )
        configured = override_settings(FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: self.profile)
        configured.enable()
        self.addCleanup(configured.disable)
        self.operator = Operator(
            self.directory.provider_id, self.directory.current, self.receipt["public_ref"]
        )
        self.fixture = setup_synthetic_fixture(
            operator_authority=self.operator,
            identity_provider=self.directory,
            synthetic_fixtures_only=True,
        )
        configured = override_settings(**self.fixture.settings())
        configured.enable()
        self.addCleanup(configured.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def ready(self):
        self.save(
            files=[
                {
                    "raw": b"synthetic pilot file",
                    "filename": "answer.txt",
                    "media_type": "text/plain",
                },
                answer_tests.audio_fixture(),
            ]
        )
        self.approve()  # Explicit existing canonical human decision fixture, not a pilot operation.
        return services.read_workbench(**self.common)

    def apply(self, action, snapshot=None, **extra):
        snap = snapshot or services.read_workbench(**self.common)
        return services.apply_action(
            **self.common,
            action=action,
            revision=snap["revision"],
            evidence_version=snap["evidence_version"],
            plan_sha256=snap["plan_sha256"],
            confirmed=True,
            **extra,
        )

    def report(self, number, outcome, **extra):
        snap = services.read_workbench(**self.common)
        part = snap["parts"][number - 1]
        return self.apply(
            "pilot_report",
            snap,
            part_id=part["id"],
            expected_state=part["state"],
            outcome=outcome,
            **extra,
        )

    def login(self):
        page = self.client.get("/casework/staff/login/")
        result = post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(result.status_code, 303, result.content)
        return self.client.get("/casework/staff/")

    def open(self, page):
        result = post(
            self.client,
            "/casework/staff/",
            {"action": "pilot_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def mutation(self, page, action, **extra):
        pins = {
            key: hidden(page, key)
            for key in ("case_ref", "revision", "evidence_version", "plan_sha256")
        }
        return post(
            self.client,
            "/casework/staff/",
            {"action": action, "confirm": "yes", **pins, **extra},
            page,
        )

    def test_shorter_browser_deadline_preserves_native_pilot_read_without_granting_approval(self):
        home = self.login()
        actor = access.current_staff(home.wsgi_request, self.directory)
        self.assertLess(actor.valid_until, self.directory.current.valid_until)
        proxy = access.RequestDirectory(
            self.directory, actor, authenticated_provider_id=self.directory.provider_id
        )
        with cases._staff_case(self.receipt["case_id"], actor.subject_id, proxy, True) as (case, _):
            authorized = services._operator(self.fixture, case, actor.subject_id, proxy, "OPEN")
            self.assertEqual(authorized, actor)
        page = self.open(home)
        self.assertIn("يلزم اعتماد بشري حالي", page.content.decode())
        self.assertNotIn(b'value="pilot_authorize"', page.content)
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_last_operator_callback_cannot_outlive_the_shorter_browser_deadline(self):
        until = timezone.now() + timedelta(seconds=2)
        actor = replace(self.directory.current, valid_until=until)
        proxy = access.RequestDirectory(
            self.directory, actor, authenticated_provider_id=self.directory.provider_id
        )
        original = self.operator.permits
        observed = []
        elapsed = patch(
            "apps.pilot_workbench.services.timezone.now", return_value=until + timedelta(seconds=1)
        )

        def expire_after_policy(**values):
            observed.append(values["action"])
            allowed = original(**values)
            elapsed.start()
            return allowed

        try:
            with (
                patch.object(self.operator, "permits", side_effect=expire_after_policy),
                self.assertRaises(cases.CaseConflict),
                cases._staff_case(self.receipt["case_id"], actor.subject_id, proxy, True) as (
                    case,
                    _,
                ),
            ):
                services._operator(self.fixture, case, actor.subject_id, proxy, "OPEN")
        finally:
            elapsed.stop()
        self.assertEqual(observed, ["OPEN"])
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.assertEqual(CaseDecision.objects.count(), 0)

    def test_native_permission_and_per_part_reports_without_json_or_auto_approval(self):
        page = self.open(self.login())
        self.assertNotIn(b'value="pilot_authorize"', page.content)
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.ready()
        page = self.open(page)
        self.assertIn(b'value="pilot_authorize"', page.content)
        page = self.mutation(page, "pilot_authorize")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(DeliveryIntent.objects.count(), 3)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        for number, outcome in ((1, "ACCEPTED"), (1, "DELIVERED"), (2, "FAILED"), (3, "DELIVERED")):
            snapshot = services.read_workbench(**self.common)
            part = snapshot["parts"][number - 1]
            page = self.mutation(
                page,
                "pilot_report",
                part_id=part["id"],
                expected_state=part["state"],
                outcome=outcome,
            )
            self.assertEqual(page.status_code, 200, page.content)
            for lease, _ in self.fixture._attempts.values():
                self.assertNotIn(lease.token.encode(), page.content)
            self.assertNotIn(b"signature_b64url", page.content)
        status = services.read_workbench(**self.common)["status"]
        self.assertEqual(status["verified_parts"], 2)
        self.assertFalse(status["delivery_verified"])
        self.assertFalse(status["read_confirmed"])
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 3)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 4)
        self.assertEqual(self.fixture._attempts, {})

    def test_no_current_approval_means_no_fixture_signature_or_queue(self):
        self.save()
        with self.assertRaises(cases.CaseConflict):
            services.apply_action(
                **self.common,
                action="pilot_authorize",
                revision=2,
                evidence_version=1,
                plan_sha256="0" * 64,
                confirmed=True,
            )
        self.assertEqual(self.fixture._return_authority._issued, {})
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.assertEqual(CaseDecision.objects.count(), 0)

    def test_flags_typed_authority_exact_verifiers_and_confirmation_closed(self):
        snap = self.ready()
        with self.assertRaises(cases.CaseConflict):
            setup_synthetic_fixture(
                operator_authority=lambda **_: True,
                identity_provider=self.directory,
                synthetic_fixtures_only=True,
            )
        for overrides in (
            {"FATWA_PILOT_WORKBENCH_ENABLED": False},
            {"FATWA_PILOT_WORKBENCH": None},
            {"FATWA_CASE_DELIVERY_APPROVAL_VERIFIER": None},
            {"FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": None},
        ):
            with override_settings(**overrides), self.assertRaises(cases.CaseConflict):
                self.apply("pilot_authorize", snap)
        with self.assertRaises(cases.CaseConflict):
            services.apply_action(
                **self.common,
                action="pilot_authorize",
                revision=snap["revision"],
                evidence_version=snap["evidence_version"],
                plan_sha256=snap["plan_sha256"],
                confirmed=False,
            )
        self.operator.allowed = False
        with self.assertRaises(cases.CaseConflict):
            self.apply("pilot_authorize", snap)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_stale_plan_versions_foreign_part_and_unsupported_capability_deny(self):
        snap = self.ready()
        changed = {**snap, "plan_sha256": "0" * 64}
        with self.assertRaises(cases.CaseConflict):
            self.apply("pilot_authorize", changed)
        changed = {**snap, "revision": snap["revision"] - 1}
        with self.assertRaises(cases.CaseConflict):
            self.apply("pilot_authorize", changed)
        self.profile = replace(
            self.profile,
            capabilities=replace(self.profile.capabilities, supported=frozenset({"text"})),
        )
        unsupported = services.read_workbench(**self.common)
        self.assertTrue(unsupported["requires_human"])
        with self.assertRaises(cases.CaseConflict):
            self.apply("pilot_authorize", unsupported)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_duplicate_confirmation_and_stale_part_form_never_retry(self):
        snap = self.ready()
        self.apply("pilot_authorize", snap)
        with self.assertRaises(cases.CaseConflict):
            self.apply("pilot_authorize", snap)
        snap = services.read_workbench(**self.common)
        part = snap["parts"][0]
        self.report(1, "ACCEPTED")
        with self.assertRaises(cases.CaseConflict):
            self.apply(
                "pilot_report",
                snap,
                part_id=part["id"],
                expected_state="STAGED",
                outcome="DELIVERED",
            )
        self.report(1, "FAILED")
        with self.assertRaises(cases.CaseConflict):
            self.report(1, "DELIVERED")
        with self.assertRaises(cases.CaseConflict):
            self.apply(
                "pilot_report",
                part_id="00000000-0000-0000-0000-000000000000",
                expected_state="STAGED",
                outcome="ACCEPTED",
            )
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 2)

    def test_scope_epoch_role_and_operator_revocation_deny_current_actions(self):
        snap = self.ready()
        original = self.directory.current
        for change in (
            {"case_keys": frozenset({"other-case"})},
            {"auth_epoch": "new-epoch"},
            {"role": "ORGANIZER_ADMIN"},
        ):
            self.directory.current = replace(original, **change)
            with self.assertRaises(cases.CaseConflict):
                self.apply("pilot_authorize", snap)
        self.directory.current = original
        self.apply("pilot_authorize", snap)
        self.operator.actions.remove("REPORT_PROVIDER")
        with self.assertRaises(cases.CaseConflict):
            self.report(1, "ACCEPTED")
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_late_revocation_rolls_back_permission_and_provider_attempt(self):
        snap = self.ready()
        original_issue = self.fixture._return_authority._issue_locked

        def revoke_after_issue(*args):
            receipt = original_issue(*args)
            self.operator.allowed = False
            return receipt

        with (
            patch.object(
                self.fixture._return_authority, "_issue_locked", side_effect=revoke_after_issue
            ),
            self.assertRaises(ValueError),
        ):
            self.apply("pilot_authorize", snap)
        self.assertEqual(DeliveryIntent.objects.count(), 0)
        self.assertEqual(self.fixture._return_authority._issued, {})
        self.operator.allowed = True
        self.apply("pilot_authorize", snap)
        original_event = self.fixture.provider_fixture.event

        def revoke_after_event(**args):
            event = original_event(**args)
            self.operator.allowed = False
            return event

        with (
            patch.object(self.fixture.provider_fixture, "event", side_effect=revoke_after_event),
            self.assertRaises(cases.CaseConflict),
        ):
            self.report(1, "ACCEPTED")
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(self.fixture._attempts, {})

    def test_restart_memory_loss_expiry_and_new_facts_never_reserve_again(self):
        self.ready()
        self.apply("pilot_authorize")
        self.report(1, "ACCEPTED")
        self.fixture._attempts.clear()  # Simulated worker memory loss; native attempt stays authoritative.
        with self.assertRaises(cases.CaseConflict):
            self.report(1, "DELIVERED")
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.fixture.expires_at = timezone.now() - timedelta(seconds=1)
        with self.assertRaises(cases.CaseConflict):
            services.read_workbench(**self.common)
        self.fixture.expires_at = timezone.now() + timedelta(minutes=20)
        before = services.read_workbench(**self.common)
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع اصطناعية جديدة",
            expected_revision=before["revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.apply(
                "pilot_report",
                before,
                part_id=before["parts"][1]["id"],
                expected_state="STAGED",
                outcome="DELIVERED",
            )
        self.assertEqual(DeliveryAttempt.objects.count(), 1)

    def test_expired_return_permission_blocks_new_attempt_without_refresh_signing(self):
        self.ready()
        self.apply("pilot_authorize")
        with patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(minutes=5)):
            with self.assertRaises(ValueError):
                self.report(1, "ACCEPTED")
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(CompositeDelivery.objects.count(), 1)
        self.assertEqual(len(self.fixture._return_authority._issued), 1)

    def test_csrf_unknown_fields_and_cross_case_forms_deny(self):
        self.ready()
        page = self.open(self.login())
        values = {
            key: hidden(page, key)
            for key in ("case_ref", "revision", "evidence_version", "plan_sha256")
        }
        result = self.client.post(
            "/casework/staff/", {**values, "action": "pilot_authorize", "confirm": "yes"}
        )
        self.assertEqual(result.status_code, 403)
        result = self.mutation(page, "pilot_authorize", key="user-supplied-key")
        self.assertEqual(result.status_code, 400)
        result = self.mutation(page, "pilot_authorize", case_ref="FT-2026-" + "A" * 20)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_concurrent_confirmation_records_one_native_plan(self):
        snap = self.ready()

        def authorize():
            try:
                try:
                    self.apply("pilot_authorize", snap)
                    return "done"
                except cases.CaseConflict:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: authorize(), range(2)))
        self.assertCountEqual(results, ["done", "denied"])
        self.assertEqual(DeliveryIntent.objects.count(), 3)
        self.assertEqual(CompositeDelivery.objects.count(), 1)
        self.assertEqual(CaseDecision.objects.count(), 1)

    def test_bootstrap_guards_run_before_any_ephemeral_key_generation(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with patch.object(Ed25519PrivateKey, "generate") as keygen:
            with self.assertRaises(cases.CaseConflict):
                setup_synthetic_fixture(
                    operator_authority=self.operator, identity_provider=self.directory
                )
            with (
                patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}),
                self.assertRaises(cases.CaseConflict),
            ):
                setup_synthetic_fixture(
                    operator_authority=self.operator,
                    identity_provider=self.directory,
                    synthetic_fixtures_only=True,
                )
            with (
                patch.object(cases, "_guard", side_effect=cases.CaseConflict("not_owned")),
                self.assertRaises(cases.CaseConflict),
            ):
                setup_synthetic_fixture(
                    operator_authority=self.operator,
                    identity_provider=self.directory,
                    synthetic_fixtures_only=True,
                )
            keygen.assert_not_called()

    def test_fresh_fixture_restart_cannot_resume_old_attempt_or_issue_replacement_permission(self):
        self.ready()
        self.apply("pilot_authorize")
        self.report(1, "ACCEPTED")
        replacement = setup_synthetic_fixture(
            operator_authority=self.operator,
            identity_provider=self.directory,
            synthetic_fixtures_only=True,
        )
        with override_settings(**replacement.settings()):
            snapshot = services.read_workbench(**self.common)
            self.assertFalse(snapshot["permission_valid"])
            self.assertTrue(snapshot["parts"][0]["pilot_memory_missing"])
            with self.assertRaises(cases.CaseConflict):
                self.report(1, "DELIVERED")
            with self.assertRaises(ValueError):
                self.report(2, "ACCEPTED")
            with self.assertRaises(cases.CaseConflict):
                self.apply("pilot_authorize")
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 1)
        self.assertEqual(len(replacement._return_authority._issued), 0)

    def test_foreign_existing_part_and_nonnext_part_do_not_reserve_any_attempt(self):
        self.ready()
        self.apply("pilot_authorize")
        with self.assertRaises(cases.CaseConflict):
            self.report(3, "ACCEPTED")
        other = cases.intake_case(
            original_question="سؤال اصطناعي مستقل",
            source_event_id="pilot-other",
            requester_id="pilot-other-requester",
            idempotency_key="pilot-other",
            synthetic_fixtures_only=True,
        )
        self.directory.grant(self.receipt["public_ref"], other["public_ref"])
        media_services.save_multipart_answer(
            **{**self.common, "case_id": other["case_id"]},
            text="جواب آخر لا ينقل بين القضايا",
            files=[answer_tests.audio_fixture()],
            expected_revision=1,
            expected_evidence_version=1,
        )
        foreign = AnswerPart.objects.get(manifest__answer__case_id=other["case_id"], ordinal=2)
        with self.assertRaises(cases.CaseConflict):
            self.apply(
                "pilot_report",
                part_id=str(foreign.pk),
                expected_state="STAGED",
                outcome="DELIVERED",
            )
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_revoked_return_authority_cannot_be_bypassed_by_report_grant(self):
        self.ready()
        self.apply("pilot_authorize")
        self.operator.actions.remove("AUTHORIZE_RETURN")
        snapshot = services.read_workbench(**self.common)
        self.assertFalse(snapshot["permission_valid"])
        with self.assertRaises(ValueError):
            self.report(1, "ACCEPTED")
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_return_fixture_internal_entry_cannot_sign_arbitrary_unlocked_payload(self):
        with self.assertRaises(cases.CaseConflict):
            self.fixture._return_authority._issue_locked(
                {}, self.directory.current, self.directory.provider_id
            )
        self.assertEqual(self.fixture._return_authority._issued, {})

    def test_return_authority_withdrawn_during_provider_report_rolls_back_attempt(self):
        self.ready()
        self.apply("pilot_authorize")
        original = self.fixture.provider_fixture.event

        def withdraw_return_permission(**kwargs):
            event = original(**kwargs)
            self.operator.actions.remove("AUTHORIZE_RETURN")
            return event

        with (
            patch.object(
                self.fixture.provider_fixture, "event", side_effect=withdraw_return_permission
            ),
            self.assertRaises(ValueError),
        ):
            self.report(1, "ACCEPTED")
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(ProviderSignatureEvidence.objects.count(), 0)
        self.assertEqual(self.fixture._attempts, {})
