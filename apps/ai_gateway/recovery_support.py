"""Nonempty AI audit/derivatives; restoration never restores a provider grant."""

import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.mufti_review.identity import IdentityUnavailable
from apps.precise_citations.test_support import FixtureAuthority as CitationAuthority
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .models import CandidateBatch, GatewayOutcome, GatewayRun
from .test_support import FEATURES, FixtureAuthority, GatewayFixture, SyntheticProvider

TABLES = tuple(model._meta.db_table for model in (GatewayRun, GatewayOutcome, CandidateBatch))
FUNCTIONS = ("ai_gateway_history_guard()",)
TRIGGERS = ("ai_gateway_run_guard", "ai_gateway_outcome_guard", "ai_gateway_batch_guard")
DENIALS = (
    "gateway_disabled",
    "task_disabled",
    "missing_gateway_authority",
    "missing_identity_directory",
    "missing_provider",
    "killed_provider",
    "revoked_source_processing",
    "revoked_fragment_processing",
    "revoked_source_read",
    "revoked_source_cite",
    "revoked_case_scope",
    "cross_actor",
)


def rows(case_id):
    queries = (
        GatewayRun.objects.filter(case_id=case_id),
        GatewayOutcome.objects.filter(run__case_id=case_id),
        CandidateBatch.objects.filter(run__case_id=case_id),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("AI recovery table is empty")
        result[query.model._meta.db_table] = sha256(
            json.dumps(values, default=str, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    return result


def populate():
    class Fixture(GatewayFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    enabled = override_settings(**FEATURES)
    enabled.enable()
    try:
        fixture.setUp()
        complete = fixture.request()
        fixture.ai_provider.error = RuntimeError("synthetic failure")
        failed = fixture.request()
        return dict(
            case={key: fixture.receipt[key] for key in ("case_id", "public_ref")},
            material={key: fixture.material[key] for key in ("version_id", "digest")},
            run_id=complete["id"],
            failed_id=failed["id"],
            original_sha256=sha256(fixture.source_text.encode()).hexdigest(),
            tables=rows(fixture.receipt["case_id"]),
        )
    finally:
        fixture.doCleanups()
        enabled.disable()


@contextmanager
def fixture_trust(pins):
    receipt = pins["case"]
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    source = LibraryAuthority(receipt["public_ref"])
    gateway = FixtureAuthority(receipt, pins["material"])
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PRECISE_CITATIONS_AUTHORITY": CitationAuthority(receipt["public_ref"]),
            "FATWA_RESEARCH_LIBRARY_AUTHORITY": source,
            "FATWA_AI_GATEWAY_AUTHORITY": gateway,
            "FATWA_AI_CITATION_PROVIDER": SyntheticProvider(pins["material"]["version_id"]),
        }
    ):
        yield (
            dict(
                case_id=receipt["case_id"],
                subject_id="editor",
                provider=directory,
                synthetic_fixtures_only=True,
            ),
            source,
            gateway,
        )


def verify_restored(pins):
    if rows(pins["case"]["case_id"]) != pins["tables"]:
        raise AssertionError("restored AI audit/derivatives changed")
    with fixture_trust(pins) as (base, source, gateway):

        def positive():
            with services.read_boundary(**base, run_id=pins["run_id"]) as result:
                if result["status"] != "SUCCEEDED" or result["provider_mode"] != "SYNTHETIC":
                    raise AssertionError("restored candidate status changed")
                entry = result["candidates"][0]
                original = entry["before"] + entry["selected"] + entry["after"]
                if sha256(original.encode()).hexdigest() != pins["original_sha256"]:
                    raise AssertionError("restored source bytes changed")

        positive()
        with services.read_boundary(**base, run_id=pins["failed_id"]) as failed:
            if failed["status"] != "PROVIDER_FAILED" or failed["candidates"]:
                raise AssertionError("restored failed attempt became a successful candidate")
        denial_checks = dict.fromkeys(DENIALS, 0)

        def deny(name, **changes):
            try:
                with services.read_boundary(**{**base, **changes}, run_id=pins["run_id"]):
                    pass
            except (cases.CaseConflict, IdentityUnavailable):
                denial_checks[name] += 1
            else:
                raise AssertionError("restored AI inferred a permission: " + name)

        for name, setting, value in (
            ("gateway_disabled", "FATWA_AI_GATEWAY_ENABLED", False),
            ("task_disabled", "FATWA_AI_CITATION_CANDIDATES_ENABLED", False),
            ("missing_gateway_authority", "FATWA_AI_GATEWAY_AUTHORITY", None),
            ("missing_identity_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_provider", "FATWA_AI_CITATION_PROVIDER", None),
            ("killed_provider", "FATWA_AI_DISABLED_PROVIDERS", {"synthetic-citation-fixture"}),
        ):
            with override_settings(**{setting: value}):
                deny(name)
        for name, kind in (
            ("revoked_source_processing", "LIBRARY"),
            ("revoked_fragment_processing", "DRAFT_FRAGMENT"),
        ):
            gateway.denied.add(("PROCESS_CONTEXT", kind))
            deny(name)
            gateway.denied.clear()
        for name, action in (("revoked_source_read", "READ"), ("revoked_source_cite", "CITE")):
            source.denied.add(action)
            deny(name)
            source.denied.clear()
        actor = base["provider"].identities["editor"]
        base["provider"].identities["editor"] = replace(actor, case_keys=frozenset())
        deny("revoked_case_scope")
        base["provider"].identities["editor"] = actor
        deny("cross_actor", subject_id="other")
        positive()
    if rows(pins["case"]["case_id"]) != pins["tables"]:
        raise AssertionError("restored AI reads modified audit or derivatives")
    return dict(
        status="PASS",
        nonempty_tables=len(TABLES),
        denied_reads=sum(denial_checks.values()),
        denied_read_count=sum(denial_checks.values()),
        denial_checks=denial_checks,
        positive_reads_after_denial=True,
        original_bytes_preserved=True,
        real_provider_quality="NOT_EVALUATED",
    )
