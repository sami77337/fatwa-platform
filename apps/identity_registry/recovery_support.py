"""Nonempty identity history; fresh authority is explicitly supplied after restore."""

import unittest
from contextlib import contextmanager

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_case_intake.models import SourceReceipt

from . import services
from .boundary import digest
from .models import (
    IdentityMembership,
    IdentityObservation,
    LinkProposal,
    Person,
    PlatformIdentity,
    RegistryOperation,
)
from .test_support import FEATURES, Authority, RegistryFixture

MODELS = (
    PlatformIdentity,
    IdentityObservation,
    Person,
    LinkProposal,
    RegistryOperation,
    IdentityMembership,
)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("identity_registry_guard()", "identity_registry_complete()")
TRIGGERS = (
    "ir_identity_guard",
    "ir_observation_guard",
    "ir_person_guard",
    "ir_proposal_guard",
    "ir_operation_guard",
    "ir_membership_guard",
    "ir_operation_complete",
)


def rows(case_ids):
    identities = IdentityObservation.objects.filter(case_id__in=case_ids).values_list(
        "identity_id", flat=True
    )
    queries = (
        PlatformIdentity.objects.filter(pk__in=identities),
        IdentityObservation.objects.filter(case_id__in=case_ids),
        Person.objects.filter(case_id__in=case_ids),
        LinkProposal.objects.filter(case_id__in=case_ids),
        RegistryOperation.objects.filter(case_id__in=case_ids),
        IdentityMembership.objects.filter(identity_id__in=identities),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("identity recovery table is empty")
        result[query.model._meta.db_table] = digest(values)
    return result


def populate():
    class Fixture(RegistryFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    enabled = override_settings(**FEATURES)
    enabled.enable()
    try:
        fixture.setUp()
        first, person_a = fixture.capture(), fixture.person("شخص استعادة أول")
        fixture.link(first, person_a)
        other_case, other = fixture.new_case()
        second, person_b = fixture.capture(other), fixture.person("شخص استعادة ثانٍ")
        fixture.link(second, person_b, other)
        preview = services.prepare(
            **fixture.common,
            kind="MERGE",
            source_person_id=person_b["id"],
            target_person_id=person_a["id"],
        )
        services.apply(
            **fixture.command(),
            preview=preview,
            reason="دمج اصطناعي موثق للاستعادة",
            confirmed=True,
        )
        preview = services.prepare(
            **fixture.common,
            kind="SPLIT",
            source_person_id=person_a["id"],
            target_person_id=person_b["id"],
            identity_ids=[second["id"]],
        )
        services.apply(
            **fixture.command(),
            preview=preview,
            reason="فصل اصطناعي موثق للاستعادة",
            confirmed=True,
        )
        services.decide(
            **fixture.command(other),
            kind="UNLINK",
            identity_id=second["id"],
            reason="سحب تحقق محفوظ في الاستعادة",
            confirmed=True,
        )
        receipts = [fixture.receipt, other_case]
        case_ids = [row["case_id"] for row in receipts]
        return {
            "cases": [{key: row[key] for key in ("case_id", "public_ref")} for row in receipts],
            "identities": {first["id"]: "VERIFIED_LINK", second["id"]: "UNLINKED"},
            "tables": rows(case_ids),
            "origins": {
                str(row.pk): row.sha256
                for row in SourceReceipt.objects.filter(evidencebinding__case_id__in=case_ids)
            },
        }
    finally:
        fixture.doCleanups()
        enabled.disable()


@contextmanager
def fixture_trust(receipts):
    refs = [row["public_ref"] for row in receipts]
    directory = bind_identity_snapshot(Directory(refs))
    authority = Authority(refs)
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_IDENTITY_REGISTRY_AUTHORITY": authority,
        }
    ):
        yield (
            dict(
                case_id=receipts[0]["case_id"],
                subject_id="editor",
                provider=directory,
                synthetic_fixtures_only=True,
            ),
            authority,
        )


def verify_restored(pins):
    case_ids = [row["case_id"] for row in pins["cases"]]
    if rows(case_ids) != pins["tables"]:
        raise AssertionError("restored identity history changed")
    with fixture_trust(pins["cases"]) as (base, authority):
        result = services.desk(**base)
        if {row["id"]: row["state"] for row in result["identities"]} != pins["identities"]:
            raise AssertionError("restored identity verification state changed")
        for identifier, expected in pins["origins"].items():
            from hashlib import sha256

            if sha256(bytes(SourceReceipt.objects.get(pk=identifier).raw)).hexdigest() != expected:
                raise AssertionError("restored original identity source changed")
        denial_checks = {
            "missing_authority": 0,
            "missing_identity_provider": 0,
            "revoked_current_reader": 0,
        }
        for key, change in (
            ("missing_authority", {"FATWA_IDENTITY_REGISTRY_AUTHORITY": None}),
            ("missing_identity_provider", {"FATWA_CASEWORK_IDENTITY_PROVIDER": None}),
        ):
            with override_settings(**change):
                try:
                    services.desk(**base)
                except cases.CaseConflict:
                    denial_checks[key] += 1
                else:
                    raise AssertionError("restored identity reader inferred trust")
        authority.denied.add("READ")
        try:
            services.desk(**base)
        except cases.CaseConflict:
            denial_checks["revoked_current_reader"] += 1
        else:
            raise AssertionError("restored identity reader ignored revocation")
        authority.denied.clear()
        if {row["id"]: row["state"] for row in services.desk(**base)["identities"]} != pins[
            "identities"
        ]:
            raise AssertionError("positive identity read failed after denial")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denial_checks": denial_checks,
        "denied_read_count": sum(denial_checks.values()),
        "positive_reads_after_denial": True,
        "merge_split_history_preserved": True,
    }
