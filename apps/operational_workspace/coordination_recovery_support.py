"""Restored administrative history needs newly supplied current role/resource grants."""

import unittest
from dataclasses import replace
from datetime import timedelta

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.case_assignments.models import AssignmentEvent, PriorityEvent
from apps.casework import services as cases
from apps.casework.models import Case

from . import coordination
from .boundary import digest
from .coordination_test_support import (
    COORDINATION_FEATURES,
    CandidatePolicy,
    CoordinationFixture,
    PriorityPolicy,
    grant_choices,
)
from .metadata_test_support import MetadataAuthority
from .recovery_support import row_pins
from .test_support import Directory

TABLES = ("case_assignments_priorityevent",)
FUNCTIONS = ("ca_priority_guard",)
TRIGGERS = ("ca_priority_guard",)


def read(pins, common):
    with coordination.projection(case_ref=pins["case_ref"], **common) as row:
        assert row["role"] == "ORGANIZER"
        assert row["assignment"]["primary_subject"] == "mufti"
        assert row["priority"]["value"] == "fixture_normal"
        assert len(row["assignment"]["history"]) == 1
        assert len(row["priority"]["history"]) == 2
        return digest(
            {
                key: row[key]
                for key in (
                    "assignment",
                    "priority",
                    "targets",
                    "priority_options",
                    "policy_sha256",
                )
            }
        )


def populate():
    class Fixture(CoordinationFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**COORDINATION_FEATURES):
        try:
            fixture.setUp()
            fixture.assign()
            fixture.prioritize()
            fixture.prioritize(
                value="fixture_normal",
                expected_version=1,
                reason="تحديث بشري محفوظ بعد الحالة الأولى",
            )
            pins = {
                "cases": fixture.receipts,
                "case_ref": fixture.target["public_ref"],
                "case_id": fixture.target["case_id"],
            }
            pins["expected"] = read(pins, fixture.common)
            pins["tables"] = row_pins(fixture.receipts)
            assert fixture.immutable_sources() == fixture.originals
            return pins
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    connection.close()
    before = row_pins(pins["cases"])
    assert before == pins["tables"]
    directory = Directory([pins["case_ref"]])
    directory.identities["mufti2"] = replace(directory.identities["mufti"], subject_id="mufti2")
    authority = MetadataAuthority(pins["cases"])
    candidates, priorities = CandidatePolicy(), PriorityPolicy()
    grant_choices(
        authority, Case.objects.get(pk=pins["case_id"]), candidates, priorities, directory
    )
    common = dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True)
    denials = {}
    with override_settings(
        **{
            **COORDINATION_FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_CASE_ASSIGNMENT_CANDIDATES": candidates,
            "FATWA_OPERATIONAL_PRIORITY_POLICY": priorities,
        }
    ):
        assert read(pins, common) == pins["expected"]

        def refuse(name):
            try:
                read(pins, common)
            except cases.CaseConflict:
                denials[name] = 1
            else:
                raise AssertionError("restored administrative history inferred current authority")

        for name, setting, value in (
            ("disabled_coordination", "FATWA_OPERATIONAL_COORDINATION_ENABLED", False),
            ("disabled_assignments", "FATWA_CASE_ASSIGNMENTS_ENABLED", False),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_operational_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_candidate_policy", "FATWA_CASE_ASSIGNMENT_CANDIDATES", None),
            ("missing_priority_policy", "FATWA_OPERATIONAL_PRIORITY_POLICY", None),
        ):
            with override_settings(**{setting: value}):
                refuse(name)
        actor = directory.identities["operator"]
        directory.identities["operator"] = replace(actor, active=False)
        refuse("revoked_current_actor")
        directory.identities["operator"] = actor
        resources = set(authority.resources)
        authority.revoke(action="READ_COORDINATION")
        refuse("revoked_coordination_read")
        authority.resources = resources
        until = authority.until
        authority.until = timezone.now() - timedelta(seconds=1)
        refuse("expired_current_grant")
        authority.until = until
        assert read(pins, common) == pins["expected"]
    assert row_pins(pins["cases"]) == before == pins["tables"]
    assert AssignmentEvent.objects.filter(case_id=pins["case_id"]).count() == 1
    assert PriorityEvent.objects.filter(case_id=pins["case_id"]).count() == 2
    return {
        "status": "PASS",
        "new_table_count": 1,
        "actual_operational_role": "ORGANIZER",
        "denial_checks": denials,
        "denied_read_count": len(denials),
        "positive_reads_after_denial": True,
        "original_sources_and_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
