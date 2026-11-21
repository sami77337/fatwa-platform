"""Fresh read-only retry-chain recovery; only public verification keys are retained."""

import unittest
from hashlib import sha256

from django.db import connection
from django.test import override_settings

from apps.answer_media import services as media
from apps.casework import services as cases
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import DeliveryAuditHead
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from tests.casework.test_core import TestDirectory

from . import selection_recovery, services
from .models import CompositeRetry
from .test_retry import FEATURES, RetryFixture

TABLES = ("composite_delivery_compositeretry",)
FUNCTIONS = ("composite_retry_guard()",)
TRIGGERS = ("composite_retry_scope", "composite_retry_immutable")


def rows(case_id):
    result = selection_recovery.rows(case_id)
    retries = list(
        CompositeRetry.objects.filter(delivery__decision__case_id=case_id).order_by("pk").values()
    )
    assert len(retries) == 2
    result[TABLES[0]] = selection_recovery.digest(retries)
    return result


def populate():
    class Fixture(RetryFixture, unittest.TestCase):
        def intake(self, suffix):
            return super().intake("bounded-retry-recovery-" + suffix)

    fixture = Fixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            parent, original = fixture.failed(3)
            fixture.retry_stage(fixture.retry_request(parent))
            first = fixture.reserve()
            fixture.outcome(first, fixture.resolve(first), "FAILED")
            fixture.retry_stage(fixture.retry_request(first))
            second = fixture.reserve()
            fixture.outcome(second, fixture.resolve(second), "DELIVERED")
            status = fixture.status()
            assert (
                status["delivery_verified"]
                and status["original_plan"]["state"] == "PARTIALLY_FAILED"
            )
            return {
                "case": {key: fixture.a[key] for key in ("case_id", "public_ref")},
                "plan_sha256": fixture.request()["plan_sha256"],
                "manifest_sha256": fixture.request()["manifest_sha256"],
                "status": status,
                "original_part_id": original["id"],
                "original_sha256": original["sha256"],
                "provider_public_key": fixture.channel_verifier._keys["ephemeral-fixture"]
                .public_bytes_raw()
                .hex(),
                "tables": rows(fixture.a["case_id"]),
            }
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    connection.close()
    case = pins["case"]
    before = rows(case["case_id"])
    assert before == pins["tables"]
    audit = selection_recovery.digest(list(DeliveryAuditHead.objects.order_by("pk").values()))
    directory = TestDirectory([case["public_ref"]])
    directory.projection_epoch = lambda: repr(
        (directory.provider_id, directory.refs, directory.role, directory.epoch)
    )
    profile = services.ChannelProfile(
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
    verifier = Ed25519ProviderEventVerifier(
        issuer="offline-composite-fixture",
        audience="synthetic-composite-delivery",
        provider=services.SIMULATOR_PROVIDER,
        trusted_public_keys={"ephemeral-fixture": bytes.fromhex(pins["provider_public_key"])},
    )
    common = dict(
        case_id=case["case_id"],
        subject_id="synthetic-mufti",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    denied = {}

    def read():
        request = services.prepare_composite_delivery(**common)
        assert request["plan_sha256"] == pins["plan_sha256"]
        assert request["manifest_sha256"] == pins["manifest_sha256"]
        status = services.composite_status(**common, verifier=verifier)
        assert status == pins["status"]
        assert status["delivery_verified"] and status["verified_parts"] == 3
        assert status["original_plan"]["state"] == "PARTIALLY_FAILED"
        assert len(status["retained_plans"]) == 3
        assert status["parts"][2]["retry_count"] == 2
        original = media.staff_read(
            part_id=pins["original_part_id"],
            subject_id=common["subject_id"],
            provider=directory,
            synthetic_fixtures_only=True,
        )
        assert sha256(original["raw"]).hexdigest() == pins["original_sha256"]

    def refused(label):
        try:
            read()
        except cases.CaseConflict:
            denied[label] = denied.get(label, 0) + 1
        else:
            raise AssertionError("restored retry chain fabricated current authority")

    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": verifier,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": lambda _: profile,
        }
    ):
        read()
        for label, name in (
            ("disabled_retry", "FATWA_COMPOSITE_RETRY_ENABLED"),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER"),
            ("missing_provider_verifier", "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER"),
            ("missing_capabilities", "FATWA_COMPOSITE_DELIVERY_CAPABILITIES"),
        ):
            with override_settings(**{name: None}):
                refused(label)
        directory.refs = frozenset()
        refused("revoked_current_reader")
        directory.refs = frozenset({case["public_ref"]})
        verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        refused("revoked_failure_verification_key")
        verifier._revoked_ids = frozenset()
        read()
    assert rows(case["case_id"]) == before == pins["tables"]
    assert (
        selection_recovery.digest(list(DeliveryAuditHead.objects.order_by("pk").values())) == audit
    )
    return {
        "status": "PASS",
        "new_table_count": 1,
        "retry_rows": 2,
        "retained_signed_plans": 3,
        "original_failed_state_retained": True,
        "original_logical_ordinal": 3,
        "retry_queue_ordinal": 1,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_queue_history_unchanged": True,
        "exact_original_bytes_preserved": True,
        "public_verification_key_only": True,
    }
