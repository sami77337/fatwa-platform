"""Immutable nonempty schedules and read-only restoration under fresh trust."""

import json
import unittest
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseSource
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .models import PublicationSchedule, ScheduleOutcome
from .test_support import FEATURES, FixtureAuthority, PublishingAuthority, ScheduleFixture

TABLES = (PublicationSchedule._meta.db_table, ScheduleOutcome._meta.db_table)
FUNCTIONS = ("ps_history_guard()",)
TRIGGERS = ("ps_schedule_guard", "ps_outcome_guard")


def rows(case_id):
    queries = (
        PublicationSchedule.objects.filter(edition__case_id=case_id),
        ScheduleOutcome.objects.filter(schedule__edition__case_id=case_id),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("empty publication schedule history")
        result[query.model._meta.db_table] = sha256(
            json.dumps(values, sort_keys=True, default=str).encode()
        ).hexdigest()
    return result


def canonical(case_id):
    values = [
        list(model.objects.filter(**query).order_by("pk").values())
        for model, query in (
            (Case, {"pk": case_id}),
            (CaseSource, {"case_id": case_id}),
            (AnswerRevision, {"case_id": case_id}),
            (CaseEvent, {"case_id": case_id}),
        )
    ]
    return sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def populate():
    class Fixture(ScheduleFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            cancelled = fixture.schedule()
            services.cancel(**fixture.common, schedule_id=cancelled["id"], confirmed=True)
            published = fixture.schedule()
            with patch(
                "django.utils.timezone.now",
                return_value=published["scheduled_at"] + timedelta(seconds=1),
            ):
                result = services.execute_due(
                    schedule_id=published["id"],
                    provider=fixture.directory,
                    synthetic_fixtures_only=True,
                )
            if result["state"] != "PUBLISHED":
                raise AssertionError("schedule seed did not actually publish")
            return {
                "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
                "states": {cancelled["id"]: "CANCELLED", published["id"]: "PUBLISHED"},
                "tables": rows(fixture.receipt["case_id"]),
                "canonical": canonical(fixture.receipt["case_id"]),
            }
        finally:
            fixture.doCleanups()


def verify_restored(pins):
    receipt = pins["case"]
    if (
        rows(receipt["case_id"]) != pins["tables"]
        or canonical(receipt["case_id"]) != pins["canonical"]
    ):
        raise AssertionError("schedule or canonical history changed")
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    authority = FixtureAuthority(receipt["public_ref"])
    common = dict(
        case_id=receipt["case_id"],
        subject_id="publisher",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    checks = {"missing_authority": 0, "missing_identity_provider": 0, "revoked_current_reader": 0}
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLICATION_SCHEDULES_AUTHORITY": authority,
            "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": PublishingAuthority(receipt["public_ref"]),
        }
    ):
        data = services.desk(**common)
        if {row["id"]: row["state"] for row in data["rows"]} != pins["states"]:
            raise AssertionError("restored schedule states differ")
        for key, setting in (
            ("missing_authority", "FATWA_PUBLICATION_SCHEDULES_AUTHORITY"),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER"),
        ):
            with override_settings(**{setting: None}):
                try:
                    services.desk(**common)
                except cases.CaseConflict:
                    checks[key] += 1
                else:
                    raise AssertionError("restored schedule invented current trust")
        original = directory.identities["publisher"]
        directory.identities["publisher"] = replace(original, case_keys=frozenset())
        try:
            services.desk(**common)
        except cases.CaseConflict:
            checks["revoked_current_reader"] += 1
        else:
            raise AssertionError("restored schedule ignored revoked current scope")
        directory.identities["publisher"] = original
        services.desk(**common)
    if (
        rows(receipt["case_id"]) != pins["tables"]
        or canonical(receipt["case_id"]) != pins["canonical"]
    ):
        raise AssertionError("restored schedule reads changed durable history")
    return {
        "status": "PASS",
        "nonempty_tables": 2,
        "denial_checks": checks,
        "denied_read_count": sum(checks.values()),
        "positive_reads_after_denial": True,
        "history_and_canonical_unchanged": True,
    }
