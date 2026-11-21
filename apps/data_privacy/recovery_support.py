"""Restore dated labels; require fresh separate authority for every current use."""

import json
import unittest
from contextlib import contextmanager
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.case_attachments.tests import new_case
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent, CaseEvidence, CaseSource
from apps.mufti_review.identity import IdentityUnavailable
from tests.casework.test_http import Directory

from . import management, services
from .catalog import LEVELS, locate
from .models import ClassificationRevision
from .test_support import Authority, PrivacyFixture

TABLES = (ClassificationRevision._meta.db_table,)
FUNCTIONS = ("dp_classification_guard()",)
TRIGGERS = ("dp_classification_guard",)
DENIALS = (
    "privacy_disabled",
    "missing_authority",
    "missing_directory",
    "revoked_read",
    "wrong_classification_level",
    "revoked_case_scope",
    "public_restricted_source",
    "search_not_inherited",
    "export_not_inherited",
    "publication_not_inherited",
    "ai_not_inherited",
    "classification_management_not_inherited",
    "unclassified_source",
)


def fingerprint(values):
    return sha256(json.dumps(list(values), default=str, sort_keys=True).encode()).hexdigest()


def rows(identifier):
    values = ClassificationRevision.objects.filter(target_kind="CASE", target_id=identifier)
    if values.count() != len(LEVELS):
        raise AssertionError("The recovered classification history must retain all four levels")
    return {TABLES[0]: fingerprint(values.order_by("number").values())}


def originals(ids):
    return {
        model._meta.db_table: fingerprint(
            model.objects.filter(**{field: ids}).order_by("pk").values()
        )
        for model, field in (
            (Case, "pk__in"),
            (CaseSource, "case_id__in"),
            (CaseEvidence, "case_id__in"),
            (CaseEvent, "case_id__in"),
        )
    }


def populate():
    class Fixture(PrivacyFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    try:
        fixture.setUp()
        for level in LEVELS:
            fixture.classify(level=level)
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            unclassified = new_case()
        ids = [fixture.receipt["case_id"], unclassified["case_id"]]
        return {
            "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
            "unclassified": {key: unclassified[key] for key in ("case_id", "public_ref")},
            "tables": rows(fixture.receipt["case_id"]),
            "originals": originals(ids),
        }
    finally:
        fixture.doCleanups()


@contextmanager
def fresh_trust(pins):
    directory, authority = Directory(), Authority()
    directory.projection_epoch = lambda: repr(directory.current)
    directory.grant(pins["case"]["public_ref"], pins["unclassified"]["public_ref"])
    with override_settings(
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_DATA_PRIVACY_ENABLED=True,
        FATWA_DATA_PRIVACY_AUTHORITY=authority,
    ):
        yield directory, authority


def verify_restored(pins):
    identifier = pins["case"]["case_id"]
    ids = [identifier, pins["unclassified"]["case_id"]]

    def unchanged():
        if rows(identifier) != pins["tables"] or originals(ids) != pins["originals"]:
            raise AssertionError("Classification restore changed the dated history or originals")

    unchanged()
    denial_checks = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (directory, authority):
        target = locate("CASE", identifier)
        holder = type("GrantHolder", (), {"authority": authority})()

        def principal():
            return services.staff_principal(directory, directory.current)

        def grant(level="RESTRICTED"):
            return PrivacyFixture.allow(holder, target, level, "READ", principal=principal())

        grant()
        common = dict(
            provider=directory,
            subject_id=directory.current.subject_id,
            synthetic_fixtures_only=True,
        )

        def read():
            return cases.read_case(case_id=identifier, **common)

        def positive():
            current = read()
            if current["public_ref"] != pins["case"]["public_ref"]:
                raise AssertionError("The recovered read returned a different original")
            history = services.history(target)
            if [row.level for row in history] != list(LEVELS):
                raise AssertionError("The immutable classification chain changed")

        def deny(name, operation):
            try:
                operation()
            except (cases.CaseConflict, IdentityUnavailable):
                denial_checks[name] += 1
            else:
                raise AssertionError("Restoration inferred privacy authority: " + name)

        positive()
        for name, setting, value in (
            ("privacy_disabled", "FATWA_DATA_PRIVACY_ENABLED", False),
            ("missing_authority", "FATWA_DATA_PRIVACY_AUTHORITY", None),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{setting: value}):
                deny(name, read)
        authority.grants.clear()
        deny("revoked_read", read)
        grant("PUBLIC")
        deny("wrong_classification_level", read)
        authority.grants.clear()
        grant()
        actor = directory.current
        directory.grant("outside-restored-case")
        deny("revoked_case_scope", read)
        directory.current = actor
        deny(
            "public_restricted_source",
            lambda: services.require("CASE", identifier, principal=services.public_principal()),
        )
        for name, action in (
            ("search_not_inherited", "SEARCH"),
            ("export_not_inherited", "EXPORT"),
            ("publication_not_inherited", "PUBLISH"),
            ("ai_not_inherited", "AI"),
        ):
            deny(
                name,
                lambda action=action: services.require(
                    "CASE", identifier, principal=principal(), action=action
                ),
            )

        def inspect():
            with management.inspect(kind="CASE", identifier=identifier, **common):
                pass

        deny("classification_management_not_inherited", inspect)
        deny(
            "unclassified_source",
            lambda: cases.read_case(case_id=pins["unclassified"]["case_id"], **common),
        )
        for mutate in (
            lambda: ClassificationRevision.objects.filter(target_id=identifier).update(
                level="PUBLIC"
            ),
            lambda: ClassificationRevision.objects.filter(target_id=identifier).delete(),
        ):
            try:
                with transaction.atomic():
                    mutate()
            except IntegrityError:
                pass
            else:
                raise AssertionError("Restored classification history accepted mutation")
        positive()
    unchanged()
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denied_reads": sum(denial_checks.values()),
        "denied_read_count": sum(denial_checks.values()),
        "denial_checks": denial_checks,
        "positive_reads_after_denial": True,
        "original_bytes_preserved": True,
        "classification_history_immutable": True,
        "restored_labels_grant_no_access": True,
    }
