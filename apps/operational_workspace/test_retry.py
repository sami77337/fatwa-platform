"""A successful exact retry resolves only its own preserved failure in operational reads."""

import copy
import secrets
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_lifecycle import services as lifecycle
from apps.case_lifecycle.models import LifecycleEvent
from apps.case_lifecycle.tests import Authority as LifecycleAuthority
from apps.casework import services as cases
from apps.casework.models import Case
from apps.composite_delivery.test_retry import FEATURES as RETRY_FEATURES
from apps.composite_delivery.test_retry import RetryFixture
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent
from tests.casework.test_http import post

from . import services, views
from .boundary import digest, source_rows
from .test_support import CREDENTIALS, FEATURES, Authority, Directory, Profiles

SETTINGS = {
    **{key: value for key, value in RETRY_FEATURES.items() if not key.startswith("DATA_UPLOAD_")},
    **FEATURES,
    "FATWA_CASE_LIFECYCLE_ENABLED": True,
}
BASE = "/casework/operations/"


@override_settings(**SETTINGS)
class OperationalRetryTests(RetryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.operator = Directory([self.a["public_ref"]])
        self.operational_authority = Authority({"delivery": self.a})
        self.operational_profiles = Profiles()
        self.operational_profiles.value = self.profile
        configured = override_settings(
            FATWA_CASE_LIFECYCLE_AUTHORITY=LifecycleAuthority(
                [self.a["public_ref"]], self.directory.provider_id
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)

    @contextmanager
    def operational(self):
        with override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.operator,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.operational_authority,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=self.operational_profiles,
        ):
            yield dict(subject_id="operator", provider=self.operator, synthetic_fixtures_only=True)

    def read(self):
        before = digest(source_rows([self.a["case_id"]]))
        with self.operational() as common:
            with services.queue_projection(**common, selected_filter="delivery") as result:
                counts = result["counts"]
            with services.detail_projection(
                **common, case_ref=self.a["public_ref"], section="delivery"
            ) as result:
                detail = result["section"]
        self.assertEqual(digest(source_rows([self.a["case_id"]])), before)
        return counts, detail

    def close(self):
        case = Case.objects.get(pk=self.a["case_id"])
        return lifecycle.command(
            **self.staff(),
            action="CLOSE",
            reason="تحقق من المحاولة اللاحقة",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_version=0,
            command_id=secrets.token_hex(16),
        )

    def repaired(self):
        parent, _ = self.failed()
        self.retry_stage(self.retry_request(parent))
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "DELIVERED")
        return parent

    def test_failure_fresh_signed_retry_and_verified_success_clear_only_operational_work_and_allow_closure(
        self,
    ):
        parent, original = self.failed()
        saved_failure = DeliveryIntent.objects.filter(pk=parent.intent_key).values().get()
        self.assertEqual(self.read()[0]["delivery"], 1)
        with self.assertRaises(cases.CaseConflict):
            self.close()
        request = self.retry_request(parent)
        self.retry_stage(request)
        self.assertEqual(self.read()[0]["delivery"], 1)
        with self.assertRaises(cases.CaseConflict):
            self.close()
        lease = self.reserve()
        part = self.resolve(lease)
        self.assertEqual(part["raw"], original["raw"])
        self.outcome(lease, part, "ACCEPTED")
        self.assertEqual(self.read()[0]["delivery"], 1)
        with self.assertRaises(cases.CaseConflict):
            self.close()
        self.outcome(lease, part, "DELIVERED")
        counts, detail = self.read()
        self.assertEqual(counts["delivery"], 0)
        self.assertFalse(detail["pending"])
        self.assertEqual(detail["failed_parts"], 0)
        self.assertEqual(detail["resolved_failed_attempts"], 1)
        history = [row for row in detail["parts"] if row["resolved_by_retry"]]
        self.assertEqual(history[0]["state"], "FAILED_REQUIRES_REVIEW")
        successor = next(row for row in detail["parts"] if row["retry_number"])
        self.assertEqual((successor["ordinal"], successor["queue_ordinal"]), (2, 1))
        self.assertEqual(self.close()["state"], "CLOSED")
        self.assertEqual(
            saved_failure, DeliveryIntent.objects.filter(pk=parent.intent_key).values().get()
        )

    def test_unbound_claim_stays_reconciliation_work_after_exact_success(self):
        self.repaired()
        self.assertEqual(self.read()[0]["delivery"], 0)
        queue.commit_approved_plan(
            receipt_id="operational-unbound-" + secrets.token_hex(8),
            nonce=secrets.token_urlsafe(32),
            approval_fingerprint=secrets.token_hex(32),
            plan_fingerprint=secrets.token_hex(32),
            case_key=self.a["public_ref"],
            answer_revision=self.request()["evidence"]["answer_revision"],
            provider="composite-simulator",
            expires_at=timezone.now() + timedelta(minutes=5),
            parts=((1, secrets.token_hex(32)),),
            verify_approval=lambda: True,
        )
        counts, detail = self.read()
        self.assertEqual(counts["delivery"], 1)
        self.assertEqual(detail["unbound_claims"], 1)
        self.assertTrue(detail["pending"])
        with self.assertRaises(cases.CaseConflict):
            self.close()
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_new_answer_success_does_not_hide_a_different_old_failed_attempt(self):
        self.failed()
        self.approve()
        self.stage()
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        counts, detail = self.read()
        self.assertEqual(counts["delivery"], 1)
        self.assertEqual(detail["failed_parts"], 1)
        self.assertEqual(detail["resolved_failed_attempts"], 0)
        with self.assertRaises(cases.CaseConflict):
            self.close()

    def test_revoked_or_disabled_retry_trust_restores_unresolved_work_without_changing_history(
        self,
    ):
        self.repaired()
        before = digest(source_rows([self.a["case_id"]]))
        with override_settings(FATWA_COMPOSITE_RETRY_ENABLED=False):
            self.assertEqual(self.read()[0]["delivery"], 1)
        self.channel_verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        self.assertEqual(self.read()[0]["delivery"], 1)
        self.channel_verifier._revoked_ids = frozenset()
        self.channel_verifier._key_status = lambda _: False
        self.assertEqual(self.read()[0]["delivery"], 1)
        self.channel_verifier._key_status = None
        self.assertEqual(self.read()[0]["delivery"], 0)
        self.assertEqual(digest(source_rows([self.a["case_id"]])), before)

    def test_native_current_organizer_read_rechecks_success_proof_and_verifier_object_after_render(
        self,
    ):
        self.repaired()
        before = digest(source_rows([self.a["case_id"]]))
        with self.operational():
            client = Client(
                enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
            )
            page = client.get(BASE + "login/")
            self.assertEqual(
                post(
                    client, BASE + "login/", {"credential": CREDENTIALS["operator"]}, page
                ).status_code,
                303,
            )
            page = client.get(BASE)
            current = post(
                client,
                BASE,
                {"action": "detail", "case_ref": self.a["public_ref"], "section": "delivery"},
                page,
            )
            self.assertContains(current, "فشل تاريخي محفوظ")
            self.assertContains(current, "ORGANIZER")
            original_render = views.render

            def revoked(*args, **kwargs):
                response = original_render(*args, **kwargs)
                self.channel_verifier._revoked_ids = frozenset({"ephemeral-fixture"})
                return response

            with patch.object(views, "render", side_effect=revoked):
                response = post(
                    client,
                    BASE,
                    {"action": "detail", "case_ref": self.a["public_ref"], "section": "delivery"},
                    page,
                )
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(self.a["public_ref"], response.content.decode())
            self.channel_verifier._revoked_ids = frozenset()
            old = settings.FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER

            def replaced(*args, **kwargs):
                response = original_render(*args, **kwargs)
                settings.FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER = copy.copy(old)
                return response

            try:
                with patch.object(views, "render", side_effect=replaced):
                    response = client.get(BASE)
                self.assertEqual(response.status_code, 409)
            finally:
                settings.FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER = old
        self.assertEqual(digest(source_rows([self.a["case_id"]])), before)
