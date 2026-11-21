"""Fresh-connection read-only recovery with retained failed/successful source history."""

import json
import unittest
from dataclasses import replace
from hashlib import sha256

from django.db import connection
from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import CaseDelivery
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
from apps.source_rights.tests import Authority as RightsAuthority

from . import services
from .boundary import canonical, history
from .models import DestinationEvent, DestinationRecord, DestinationVersion
from .signatures import DestinationOutcomeVerifier
from .test_support import (
    FEATURES,
    PROFILES,
    Directory,
    Fixture,
    FixtureAuthority,
    PublicationAuthority,
)

TABLES = tuple(
    model._meta.db_table for model in (DestinationRecord, DestinationVersion, DestinationEvent)
)
FUNCTIONS = ("pd_source_pin(uuid)", "pd_record_guard()", "pd_history_guard()")
TRIGGERS = ("pd_record_guard", "pd_version_guard", "pd_event_guard")


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def owned(case_id):
    return {
        name: [[str(row["id"]), digest(row)] for row in rows]
        for name, rows in zip(TABLES, history(case_id), strict=True)
    }


def source_rows(case):
    queries = (
        CaseDelivery.objects.filter(decision__case_id=case["case_id"]),
        ApprovalClaim.objects.filter(case_key=case["public_ref"]),
        SignedDeliveryContext.objects.filter(approval__case_key=case["public_ref"]),
        DeliveryIntent.objects.filter(case_key=case["public_ref"]),
        DeliveryAttempt.objects.filter(intent__case_key=case["public_ref"]),
        ProviderReceipt.objects.filter(intent__case_key=case["public_ref"]),
        ProviderSignatureEvidence.objects.filter(receipt__intent__case_key=case["public_ref"]),
        DeliveryAuditEvent.objects.filter(intent__case_key=case["public_ref"]),
    )
    rows = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("Destination proof must retain nonempty original delivery history")
        rows[query.model._meta.db_table] = digest(values)
    return {"canonical_and_sources": digest(canonical([case["case_id"]])), "delivery": rows}


def projection(common):
    with services.desk_projection(**common) as result:
        return {
            "external_publication_verified": result["external_publication_verified"],
            "records": [
                {
                    "id": record["id"],
                    "destination": record["destination"],
                    "current": record["current_published"]["id"]
                    if record["current_published"]
                    else None,
                    "versions": [
                        {
                            key: row[key]
                            for key in (
                                "id",
                                "number",
                                "digest",
                                "source_id",
                                "source_sha256",
                                "plan_sha256",
                                "profile_sha256",
                                "state",
                                "copy",
                                "event_count",
                                "history",
                            )
                        }
                        for row in record["versions"]
                    ],
                }
                for record in result["records"]
            ],
        }


def populate():
    class Seed(Fixture, unittest.TestCase):
        pass

    fixture = Seed()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            fixture.seed_delivery()
            website = fixture.prepare(fixture.select())
            channel = fixture.prepare(fixture.select("TELEGRAM_CHANNEL", fixture.second))
            fixture.observe(website, "ACCEPTED")
            fixture.observe(website)
            fixture.observe(channel, "FAILED")
            corrected = fixture.prepare(
                fixture.select("TELEGRAM_CHANNEL", fixture.second, expected_version=1)
            )
            fixture.observe(corrected)
            case = {key: fixture.receipt[key] for key in ("case_id", "public_ref")}
            return {
                "case": case,
                "owned": owned(case["case_id"]),
                "source_rows": source_rows(case),
                "projection_sha256": digest(projection(fixture.common)),
                "public_key": fixture.signer.public_key().public_bytes_raw().hex(),
                "source_bodies": [fixture.first.body, fixture.second.body],
            }
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    connection.close()
    case = pins["case"]
    before = owned(case["case_id"])
    if before != pins["owned"] or source_rows(case) != pins["source_rows"]:
        raise AssertionError("Restored destination/source/delivery history differs")
    audit_before = digest(list(DeliveryAuditHead.objects.order_by("pk").values()))
    directory = Directory([case["public_ref"]])
    authority = FixtureAuthority(case["public_ref"])
    source_authority = PublicationAuthority(case["public_ref"])
    verifier = DestinationOutcomeVerifier(
        issuer="synthetic-publication-fixture",
        trusted_public_keys={"ephemeral-fixture": bytes.fromhex(pins["public_key"])},
    )
    common = dict(
        case_id=case["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    denied = {}

    def refused(label):
        try:
            projection(common)
        except cases.CaseConflict:
            denied[label] = 1
        else:
            raise AssertionError("Restored destination reader ignored " + label)

    def no_copy(label, destination=None):
        result = projection(common)
        rows = [
            record
            for record in result["records"]
            if destination is None or record["destination"] == destination
        ]
        if not rows or any(
            record["current"] is not None
            or any(row["copy"] is not None for row in record["versions"])
            for record in rows
        ):
            raise AssertionError(
                "Restored destination projection exposed unavailable content: " + label
            )
        denied[label] = 1

    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLICATION_DESTINATIONS_AUTHORITY": authority,
            "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": source_authority,
            "FATWA_SOURCE_RIGHTS_AUTHORITY": RightsAuthority(case["public_ref"]),
            "FATWA_PUBLICATION_DESTINATION_PROFILES": PROFILES,
            "FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER": verifier,
        }
    ):
        result = projection(common)
        if digest(result) != pins["projection_sha256"]:
            raise AssertionError("Restored exact destination copies or history differ")
        if [len(record["versions"]) for record in result["records"]] != [1, 2] or result[
            "external_publication_verified"
        ] is not False:
            raise AssertionError("Recovery confused a simulator with external publication")
        for name, label in (
            ("FATWA_PUBLICATION_DESTINATIONS_AUTHORITY", "missing_destination_authority"),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", "missing_current_identity"),
            ("FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", "missing_source_publication_authority"),
            ("FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER", "missing_signature_trust"),
        ):
            with override_settings(**{name: None}):
                refused(label)
        authority.denied.add("READ")
        refused("revoked_current_reader_grant")
        authority.denied.clear()
        directory.identities["publisher"] = replace(
            directory.identities["publisher"], auth_epoch="epoch-2"
        )
        no_copy("changed_original_publisher_epoch")
        directory.identities["publisher"] = replace(
            directory.identities["publisher"], auth_epoch="epoch-1"
        )
        verifier._revoked_ids = frozenset({"ephemeral-fixture"})
        no_copy("revoked_simulator_key")
        verifier._revoked_ids = frozenset()
        with override_settings(
            FATWA_PUBLICATION_DESTINATION_PROFILES=(
                replace(PROFILES[0], revision="site.v2"),
                PROFILES[1],
            )
        ):
            no_copy("changed_exact_destination_profile", "WEBSITE")
            unaffected = projection(common)["records"][1]
            if unaffected["current"] is None:
                raise AssertionError("Website profile change disabled the independent channel")
        with override_settings(FATWA_SOURCE_RIGHTS_ENABLED=False):
            no_copy("unavailable_current_source_rights")
        if digest(projection(common)) != pins["projection_sha256"]:
            raise AssertionError("Positive current read did not recover after temporary denial")
    if (
        owned(case["case_id"]) != before
        or source_rows(case) != pins["source_rows"]
        or digest(list(DeliveryAuditHead.objects.order_by("pk").values())) != audit_before
    ):
        raise AssertionError("Read-only destination recovery wrote state")
    return {
        "table_count": 3,
        "record_count": 2,
        "version_count": 3,
        "event_count": 13,
        "denied_read_count": len(denied),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
        "source_and_delivery_rows_unchanged": True,
        "fresh_connection": True,
        "distinct_destination_source_versions": True,
        "failed_original_history_retained": True,
        "external_publication_verified": False,
    }
