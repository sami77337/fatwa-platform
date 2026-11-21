"""Restored lesson proposals and decisions require fresh scoped operational grants."""

import unittest
from contextlib import contextmanager
from dataclasses import replace

from django.db import connection
from django.test import override_settings

from apps.casework import services as cases
from apps.scholarly_links.models import CaseLessonLink, LessonVersion

from . import lesson_links
from .boundary import digest
from .lesson_test_support import (
    LESSON_FEATURES,
    LessonAuthority,
    LessonDomainAuthority,
    LessonFixture,
    grant_lessons,
)
from .recovery_support import row_pins
from .test_support import Directory, Profiles

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def read(pins, common):
    with lesson_links.projection(case_ref=pins["case_ref"], **common) as result:
        assert result["role"] == "ORGANIZER"
        assert len(result["links"]) == len(result["catalog"]) == 2
        assert {row["state"] for row in result["links"]} == {"APPROVE", "WITHDRAW"}
        return {
            "links": digest(result["links"]),
            "catalog": digest(result["catalog"]),
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
        }


@contextmanager
def current_trust(pins):
    directory = Directory(
        [row["public_ref"] for key, row in pins["cases"].items() if key != "unscoped"]
    )
    authority, domain = LessonAuthority(pins["cases"]), LessonDomainAuthority()
    versions = list(
        LessonVersion.objects.select_related("lesson__series").filter(pk__in=pins["versions"])
    )
    grant_lessons(authority, domain, pins["cases"]["notes"], versions)
    with override_settings(
        **{
            **LESSON_FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_SCHOLARLY_LINKS_AUTHORITY": domain,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": Profiles(),
        }
    ):
        yield (
            dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True),
            authority,
            domain,
        )


def populate():
    class Fixture(LessonFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**LESSON_FEATURES):
        try:
            fixture.setUp()
            fixture.propose_lesson()
            fixture.review_lesson()
            fixture.propose_lesson(
                lesson_version_id=str(fixture.descriptive.pk),
                lesson_sha256=fixture.descriptive.sha256,
                start_ms=None,
                end_ms=None,
            )
            second = CaseLessonLink.objects.get(
                case_id=fixture.target["case_id"], lesson_version=fixture.descriptive
            )
            fixture.review_lesson(link=second)
            fixture.review_lesson(link=second, action="WITHDRAW")
            assert fixture.immutable_lesson_sources() == fixture.lesson_originals
            pins = {
                "cases": fixture.receipts,
                "case_ref": fixture.target["public_ref"],
                "versions": [str(fixture.version.pk), str(fixture.descriptive.pk)],
            }
            pins["expected"] = read(pins, fixture.common)
            pins["tables"] = row_pins(fixture.receipts)
            return pins
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    connection.close()
    before = row_pins(pins["cases"])
    assert before == pins["tables"]
    denied = {}
    with current_trust(pins) as (common, authority, domain):
        assert read(pins, common) == pins["expected"]

        def refusal(kind):
            try:
                with lesson_links.projection(case_ref=pins["case_ref"], **common):
                    pass
            except cases.CaseConflict:
                denied[kind] = denied.get(kind, 0) + 1
            else:
                raise AssertionError("restored lesson history inferred missing current authority")

        for kind, name, value in (
            ("disabled_lesson_feature", "FATWA_OPERATIONAL_LESSON_LINKS_ENABLED", False),
            ("disabled_scholarly_links", "FATWA_SCHOLARLY_LINKS_ENABLED", False),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_operational_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_lesson_authority", "FATWA_SCHOLARLY_LINKS_AUTHORITY", None),
        ):
            with override_settings(**{name: value}):
                refusal(kind)
        directory = common["provider"]
        actor = directory.identities["operator"]
        directory.identities["operator"] = replace(actor, active=False)
        refusal("revoked_current_identity")
        directory.identities["operator"] = actor
        sections, rules = set(authority.grants), set(authority.lesson_rules)
        for action in ("READ_CASE", "READ_LESSON_LINKS"):
            authority.revoke(action=action, case_ref=pins["case_ref"])
            refusal("revoked_" + action.lower())
            authority.grants = set(sections)
        authority.revoke(action="READ_CASE", case_ref=pins["cases"]["lessons"]["public_ref"])
        with lesson_links.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["links"] == result["catalog"] == []
        denied["revoked_target_case_read"] = 1
        authority.grants = set(sections)
        for action in ("READ_OPERATIONAL_LESSON", "READ_LESSON_LINK"):
            authority.revoke(action=action)
            with lesson_links.projection(case_ref=pins["case_ref"], **common) as result:
                assert result["links"] == []
                if action == "READ_OPERATIONAL_LESSON":
                    assert result["catalog"] == []
            denied["revoked_" + action.lower()] = 1
            authority.lesson_rules = set(rules)
        domain_rules = set(domain.rules)
        domain.rules = {
            row for row in domain.rules if not (row[0] == "operator" and row[3] == "READ_LESSON")
        }
        with lesson_links.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["links"] == result["catalog"] == []
        denied["revoked_domain_lesson_read"] = 1
        domain.rules = domain_rules
        assert read(pins, common) == pins["expected"]
    assert row_pins(pins["cases"]) == before == pins["tables"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "lesson_link_count": 2,
        "preserved_review_and_withdrawal": True,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_sources_and_immutable_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
