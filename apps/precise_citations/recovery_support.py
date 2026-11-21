"""Nonempty citation lineage; restored reads use fresh explicitly supplied trust."""

import json
import unittest
import uuid
from contextlib import contextmanager
from hashlib import sha256

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library import services as library
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .models import CitationAnchor, CitationReview, CitationSet
from .test_support import FEATURES, CitationFixture, FixtureAuthority

TABLES = tuple(model._meta.db_table for model in (CitationSet, CitationAnchor, CitationReview))
FUNCTIONS = ("precise_history_guard()", "precise_complete()")
TRIGGERS = ("precise_set_guard", "precise_anchor_guard", "precise_review_guard", "precise_complete")


def rows(case_id):
    queries = (
        CitationSet.objects.filter(answer__case_id=case_id),
        CitationAnchor.objects.filter(citation_set__answer__case_id=case_id),
        CitationReview.objects.filter(citation_set__answer__case_id=case_id),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("citation recovery table is empty")
        result[query.model._meta.db_table] = sha256(
            json.dumps(values, default=str, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    return result


def populate():
    class Fixture(CitationFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    enabled = override_settings(**FEATURES)
    enabled.enable()
    try:
        fixture.setUp()
        first = fixture.review_citations(fixture.save_citations())
        selected = fixture.selection()
        selected.update(
            previous_id=first["entries"][0]["id"],
            correction_reason="تصحيح موثق لا يمحو النسخة السابقة",
        )
        second = fixture.save_citations(
            selections=[selected], expected_revision=2, request_key=uuid.uuid4()
        )
        second = fixture.review_citations(second, expected_revision=3)
        return {
            "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
            "sets": [first["id"], second["id"]],
            "latest": second["id"],
            "material": fixture.material["version_id"],
            "text": fixture.answer_text,
            "original_sha256": fixture.material["file"]["sha256"],
            "tables": rows(fixture.receipt["case_id"]),
        }
    finally:
        fixture.doCleanups()
        enabled.disable()


@contextmanager
def fixture_trust(receipt):
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    source = LibraryAuthority(receipt["public_ref"])
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PRECISE_CITATIONS_AUTHORITY": FixtureAuthority(receipt["public_ref"]),
            "FATWA_RESEARCH_LIBRARY_AUTHORITY": source,
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
        )


def verify_restored(pins):
    if rows(pins["case"]["case_id"]) != pins["tables"]:
        raise AssertionError("restored citation lineage changed")
    with fixture_trust(pins["case"]) as (base, authority):
        for identifier in pins["sets"]:
            data = services.read(**base, set_id=identifier, usage="EXPORT")
            if data["answer_text"] != pins["text"] or data["review"]["actor"] != "other":
                raise AssertionError("restored reviewed citation changed")
        data = services.read(**base, set_id=pins["latest"])
        if data["previous_id"] != pins["sets"][0] or not data["entries"][0]["previous_id"]:
            raise AssertionError("restored correction history lost")
        original = library.file_content(**base, version_id=pins["material"], usage="READ")
        if sha256(original["raw"]).hexdigest() != pins["original_sha256"]:
            raise AssertionError("restored original changed")
        denial_checks = {"missing_authority": 0, "withdrawn_source_cite": 0}
        with override_settings(FATWA_PRECISE_CITATIONS_AUTHORITY=None):
            try:
                services.read(**base, set_id=pins["latest"])
            except cases.CaseConflict:
                denial_checks["missing_authority"] += 1
            else:
                raise AssertionError("restored citations inferred an authority")
        authority.denied.add("CITE")
        try:
            services.read(**base, set_id=pins["latest"])
        except cases.CaseConflict:
            denial_checks["withdrawn_source_cite"] += 1
        else:
            raise AssertionError("restored citations ignored current source withdrawal")
        authority.denied.clear()
        services.read(**base, set_id=pins["latest"], usage="EXPORT")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denied_reads": sum(denial_checks.values()),
        "denied_read_count": sum(denial_checks.values()),
        "denial_checks": denial_checks,
        "positive_reads_after_denial": True,
        "reviewed_versions": 2,
    }
