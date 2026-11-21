"""Existing metadata/taxonomy journals reopen only under newly supplied exact grants."""

import unittest
from contextlib import contextmanager
from dataclasses import replace

from django.db import connection
from django.test import override_settings

from apps.casework import services as cases
from apps.development_taxonomy.models import TreeVersion

from . import metadata
from .metadata_test_support import (
    METADATA_FEATURES,
    ClassificationAuthority,
    MetadataAuthority,
    MetadataFixture,
    grant_metadata,
)
from .recovery_support import row_pins
from .test_support import Directory, Profiles

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def read(pins, common):
    with metadata.projection(case_ref=pins["case_ref"], **common) as result:
        assert result["role"] == "ORGANIZER"
        assert result["current_classification"]["current"] is True
        assert len(result["classifications"]) == 1
        return {
            key: result[key]
            for key in (
                "tags",
                "question_types",
                "metadata_version",
                "classification_version",
                "current_classification",
            )
        }


@contextmanager
def current_trust(pins):
    directory = Directory(
        [row["public_ref"] for key, row in pins["cases"].items() if key != "unscoped"]
    )
    authority, domain = MetadataAuthority(pins["cases"]), ClassificationAuthority()
    version = TreeVersion.objects.select_related("tree").get(pk=pins["version_id"])
    grant_metadata(authority, domain, pins["cases"]["notes"], version)
    with override_settings(
        **{
            **METADATA_FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY": domain,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": Profiles(),
        }
    ):
        yield (
            dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True),
            authority,
            domain,
        )


def populate():
    class Fixture(MetadataFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**METADATA_FEATURES):
        try:
            fixture.setUp()
            fixture.update_metadata()
            fixture.update_metadata(field="question_types", values=["RULING", "TIME"])
            fixture.classify()
            assert fixture.immutable_metadata_sources() == fixture.metadata_originals
            pins = {
                "cases": fixture.receipts,
                "case_ref": fixture.target["public_ref"],
                "version_id": str(fixture.version.pk),
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
    with current_trust(pins) as (common, authority, _domain):
        assert read(pins, common) == pins["expected"]

        def refusal(kind):
            try:
                with metadata.projection(case_ref=pins["case_ref"], **common):
                    pass
            except cases.CaseConflict:
                denied[kind] = denied.get(kind, 0) + 1
            else:
                raise AssertionError("restored metadata inferred a missing current grant")

        for kind, name, value in (
            ("disabled_metadata_feature", "FATWA_OPERATIONAL_METADATA_ENABLED", False),
            ("disabled_organization", "FATWA_CASE_ORGANIZATION_ENABLED", False),
            ("disabled_workspace", "FATWA_OPERATIONAL_WORKSPACE_ENABLED", False),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_operational_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_taxonomy_authority", "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY", None),
        ):
            with override_settings(**{name: value}):
                refusal(kind)
        directory = common["provider"]
        actor = directory.identities["operator"]
        directory.identities["operator"] = replace(actor, active=False)
        refusal("revoked_current_identity")
        directory.identities["operator"] = actor
        grants = set(authority.grants)
        for action in ("READ_CASE", "READ_METADATA"):
            authority.revoke(action=action, case_ref=pins["case_ref"])
            refusal("revoked_" + action.lower())
            authority.grants = set(grants)
        resources = set(authority.resources)
        authority.revoke(action="READ_CLASSIFICATION")
        with metadata.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["classifications"] == [] and result["current_classification"] is None
        denied["revoked_exact_classification_read"] = 1
        authority.resources = resources
        assert read(pins, common) == pins["expected"]
    assert row_pins(pins["cases"]) == before == pins["tables"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "metadata_version": pins["expected"]["metadata_version"],
        "classification_version": pins["expected"]["classification_version"],
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_sources_and_immutable_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
