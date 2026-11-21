"""Read restored explicit choices using fresh current trust and public keys only."""

import json
import unittest
from hashlib import sha256

from django.db import connection
from django.test import override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseSource
from apps.delivery_planner.planner import Capabilities
from apps.delivery_queue.models import (
    ApprovalClaim,
    DeliveryAttempt,
    DeliveryAuditEvent,
    DeliveryAuditHead,
    DeliveryIntent,
    ProviderReceipt,
    ProviderSignatureEvidence,
    SignedDeliveryContext,
)
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from tests.casework.test_core import TestDirectory

from . import services
from .models import CompositeDelivery
from .test_selection import FEATURES, SelectionFixture

# Existing queue/answer tables already belong to the base recovery schema.
TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def _default(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"binary_sha256": sha256(bytes(value)).hexdigest()}
    return str(value)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=_default).encode()).hexdigest()


def rows(case_id):
    case = Case.objects.get(pk=case_id)
    queries = (
        Case.objects.filter(pk=case_id),
        CaseSource.objects.filter(case_id=case_id),
        AnswerRevision.objects.filter(case_id=case_id),
        CaseDecision.objects.filter(case_id=case_id),
        CaseEvent.objects.filter(case_id=case_id),
        AnswerManifest.objects.filter(answer__case_id=case_id),
        AnswerPart.objects.filter(manifest__answer__case_id=case_id),
        CompositeDelivery.objects.filter(decision__case_id=case_id),
        ApprovalClaim.objects.filter(case_key=case.public_ref),
        SignedDeliveryContext.objects.filter(approval__case_key=case.public_ref),
        DeliveryIntent.objects.filter(case_key=case.public_ref),
        DeliveryAttempt.objects.filter(intent__case_key=case.public_ref),
        DeliveryAuditEvent.objects.filter(intent__case_key=case.public_ref),
        ProviderReceipt.objects.filter(intent__case_key=case.public_ref),
        ProviderSignatureEvidence.objects.filter(receipt__intent__case_key=case.public_ref),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("selected-delivery recovery seed has an empty history")
        result[query.model._meta.db_table] = digest(values)
    return result


def populate():
    class Fixture(SelectionFixture, unittest.TestCase):
        def intake(self, suffix):
            return super().intake("explicit-choice-recovery-" + suffix)

    fixture = Fixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            selected = fixture.chosen()
            fixture.stage_chosen()
            lease = fixture.reserve()
            part = fixture.resolve(lease)
            event = fixture.simulator.event(lease=lease, part=part, reported="DELIVERED")
            services.record_composite_event(
                **fixture.staff(), lease=lease, event=event, verifier=fixture.channel_verifier
            )
            result = services.composite_status(**fixture.staff(), verifier=fixture.channel_verifier)
            assert result["delivery_verified"] and result["expected_parts"] == 1
            return {
                "case": {key: fixture.a[key] for key in ("case_id", "public_ref")},
                "selection_mode": "TEXT_ONLY",
                "plan_sha256": selected["plan_sha256"],
                "manifest_sha256": selected["manifest_sha256"],
                "omitted_parts": selected["omitted_parts"],
                "provider_public_key": fixture.channel_verifier._keys["ephemeral-fixture"]
                .public_bytes_raw()
                .hex(),
                "tables": rows(fixture.a["case_id"]),
            }
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    receipt = pins["case"]
    connection.close()
    before = rows(receipt["case_id"])
    assert before == pins["tables"]
    audit_before = digest(list(DeliveryAuditHead.objects.order_by("pk").values()))
    directory = TestDirectory([receipt["public_ref"]])
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
        case_id=receipt["case_id"],
        subject_id="synthetic-mufti",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    denied = {}

    def read():
        prepared = services.prepare_composite_delivery(**common)
        assert prepared["selection_mode"] == "TEXT_ONLY"
        assert prepared["plan_sha256"] == pins["plan_sha256"]
        assert prepared["manifest_sha256"] == pins["manifest_sha256"]
        assert prepared["omitted_parts"] == pins["omitted_parts"]
        status = services.composite_status(**common, verifier=verifier)
        assert status["delivery_verified"] and status["expected_parts"] == 1
        assert [part["kind"] for part in status["parts"]] == ["TEXT"]
        for part in pins["omitted_parts"]:
            original = media.staff_read(
                **{key: value for key, value in common.items() if key != "case_id"},
                part_id=part["id"],
            )
            assert sha256(original["raw"]).hexdigest() == part["sha256"]

    def refused(kind):
        try:
            read()
        except cases.CaseConflict:
            denied[kind] = denied.get(kind, 0) + 1
        else:
            raise AssertionError("restored explicit choice fabricated current authority")

    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": lambda _: profile,
        }
    ):
        read()
        for key, name, value in (
            ("disabled_choices", "FATWA_COMPOSITE_CHOICES_ENABLED", False),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_capabilities", "FATWA_COMPOSITE_DELIVERY_CAPABILITIES", None),
        ):
            with override_settings(**{name: value}):
                refused(key)
        directory.refs = frozenset()
        refused("revoked_current_reader")
        directory.refs = frozenset({receipt["public_ref"]})
        read()
    assert rows(receipt["case_id"]) == before == pins["tables"]
    assert digest(list(DeliveryAuditHead.objects.order_by("pk").values())) == audit_before
    return {
        "status": "PASS",
        "new_table_count": 0,
        "selection_mode": "TEXT_ONLY",
        "original_parts": 3,
        "selected_parts": 1,
        "exact_omitted_originals_preserved": True,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_queue_history_unchanged": True,
        "public_verification_key_only": True,
    }
