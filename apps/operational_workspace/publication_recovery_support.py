"""Restored publication decisions preserve history without restoring grants or release."""

import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationEdition

from . import publication
from .boundary import digest
from .publication_test_support import (
    PUBLICATION_FEATURES,
    PublicationDomainAuthority,
    PublicationFixture,
    PublicationGrants,
    grant_publication,
)
from .recovery_support import row_pins
from .test_support import Directory, Profiles

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def read(pins, common):
    with publication.projection(case_ref=pins["case_ref"], **common) as result:
        assert result["role"] == "ORGANIZER" and len(result["editions"]) == 1
        row = result["editions"][0]
        assert row["state"] == "WITHDRAWN" and row["subject_id"] == "mufti"
        assert [event["action"] for event in row["history"]] == ["REVIEW", "APPROVE", "WITHDRAW"]
        assert [event["subject_id"] for event in row["history"]] == ["operator", "admin", "admin"]
        return {
            "editions": digest(result["editions"]),
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
        }


@contextmanager
def current_trust(pins):
    directory = Directory(
        [row["public_ref"] for key, row in pins["cases"].items() if key != "unscoped"]
    )
    authority, domain = PublicationGrants(pins["cases"]), PublicationDomainAuthority()
    edition = PublicationEdition.objects.get(pk=pins["edition_id"])
    grant_publication(authority, domain, pins["cases"]["transcripts"], [edition])
    with override_settings(
        **{
            **PUBLICATION_FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": domain,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": Profiles(),
        }
    ):
        yield (
            dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True),
            authority,
            domain,
        )


def populate():
    class Fixture(PublicationFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**PUBLICATION_FEATURES):
        try:
            fixture.setUp()
            fixture.publication_decide()
            fixture.publication_decide(subject="admin", action="APPROVE")
            fixture.publication_decide(subject="admin", action="WITHDRAW")
            assert fixture.immutable_publication_sources() == fixture.publication_originals
            pins = {
                "cases": fixture.receipts,
                "case_ref": fixture.target["public_ref"],
                "edition_id": str(fixture.edition.pk),
                "content_sha256": fixture.edition.content_sha256,
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
                with publication.projection(case_ref=pins["case_ref"], **common):
                    pass
            except cases.CaseConflict:
                denied[kind] = 1
            else:
                raise AssertionError("restored publication inferred missing current grants")

        class Unversioned(PublicationAuthority):
            def permits(self, **values):
                return True

        for kind, name, value in (
            ("disabled_publication_manager", "FATWA_OPERATIONAL_PUBLICATION_ENABLED", False),
            ("disabled_publication", "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_operational_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_domain_authority", "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None),
            (
                "unversioned_domain_authority",
                "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY",
                Unversioned(),
            ),
        ):
            with override_settings(**{name: value}):
                refusal(kind)
        directory = common["provider"]
        actor = directory.identities["operator"]
        directory.identities["operator"] = replace(actor, active=False)
        refusal("revoked_current_identity")
        directory.identities["operator"] = actor
        sections, rules = set(authority.grants), set(authority.publication_rules)
        for action in ("READ_CASE", "READ_PUBLICATION_MANAGER"):
            authority.revoke(action=action, case_ref=pins["case_ref"])
            refusal("revoked_" + action.lower())
            authority.grants = set(sections)
        authority.revoke(action="READ_PUBLICATION_EDITION")
        with publication.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["editions"] == []
        denied["revoked_exact_edition_read"] = 1
        authority.publication_rules = rules
        domain.denied.add(("operator", "READ"))
        with publication.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["editions"] == []
        denied["revoked_domain_read"] = 1
        domain.denied.clear()
        until = authority.until
        authority.until = timezone.now() - timedelta(seconds=1)
        refusal("expired_current_operational_grants")
        authority.until = until
        directory.identities["operator"] = replace(
            actor, case_keys=actor.case_keys - {pins["case_ref"]}
        )
        refusal("removed_current_case_scope")
        directory.identities["operator"] = actor
        assert read(pins, common) == pins["expected"]
    assert row_pins(pins["cases"]) == before == pins["tables"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "publication_edition_count": 1,
        "mufti_prepared_body_unchanged": True,
        "preserved_review_approval_and_withdrawal": True,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_sources_and_immutable_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
