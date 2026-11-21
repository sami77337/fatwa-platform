"""Restored FT references need fresh explicit disclosure and current source trust."""

import unittest
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.experimental_publication.tests import Directory
from apps.public_answer_media.boundaries import core_state
from apps.public_answer_media.recovery_support import _canonical, _digest
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_rights.tests import Authority as SourceAuthority

from . import fatwa_references as references
from . import services as preview
from .policy import PreviewPolicy, PublicationGrant
from .reference_test_support import FEATURES, ReferenceFixture

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


class _Seed(ReferenceFixture, unittest.TestCase):
    pass


def _source(case_id):
    return [_canonical(case_id), _digest(core_state(case_id))]


def _text(result):
    return sha256(result["edition"]["body"].encode()).hexdigest()


def populate():
    with override_settings(**FEATURES):
        seed = _Seed()
        try:
            seed.setUp()
            with references.projection(reference=seed.receipt["public_ref"]) as result:
                body = _text(result)
            return {
                "case_id": seed.receipt["case_id"],
                "case_ref": seed.receipt["public_ref"],
                "publication_id": str(seed.publication.pk),
                "publication_sha256": seed.publication.content_sha256,
                "published_text_sha256": body,
                "original_part_id": str(seed.part.pk),
                "original_sha256": seed.part.sha256,
                "source_pins": _source(seed.receipt["case_id"]),
            }
        finally:
            seed.doCleanups()


def verify_restored(pins):
    before = _source(pins["case_id"])
    assert before == pins["source_pins"]
    directory = bind_identity_snapshot(Directory([pins["case_ref"]]))
    deadline = timezone.now() + timedelta(minutes=20)
    selected = references.PublicFatwaReferences(
        (
            references.FatwaReferenceGrant(
                pins["case_ref"],
                pins["publication_id"],
                pins["publication_sha256"],
                directory.provider_id,
                "publisher",
                "epoch-1",
            ),
        ),
        deadline,
        True,
    )
    publication_policy = PreviewPolicy(
        (PublicationGrant(pins["publication_id"], pins["publication_sha256"]),), (), deadline, True
    )
    denied = {}

    def positive():
        with references.projection(reference=pins["case_ref"]) as result:
            assert result["fatwa_reference"] == pins["case_ref"]
            assert result["edition"]["id"] == pins["publication_id"]
            assert _text(result) == pins["published_text_sha256"]
        assert (
            sha256(
                media.raw_for_part(AnswerPart.objects.get(pk=pins["original_part_id"]))
            ).hexdigest()
            == pins["original_sha256"]
        )

    def negative(key):
        try:
            with references.projection(reference=pins["case_ref"]):
                pass
        except preview.PreviewUnavailable:
            denied[key] = 1
        else:
            raise AssertionError("restored public reference inferred current trust")

    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLIC_FATWA_REFERENCES": selected,
            "FATWA_LIBRARY_PREVIEW_POLICY": publication_policy,
            "FATWA_SOURCE_RIGHTS_AUTHORITY": SourceAuthority(pins["case_ref"]),
        }
    ):
        positive()
        for key, field, value in (
            ("disabled_feature", "FATWA_REFERENCE_LOOKUP_ENABLED", False),
            ("missing_reference_policy", "FATWA_PUBLIC_FATWA_REFERENCES", None),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_publication_grant", "FATWA_LIBRARY_PREVIEW_POLICY", None),
            ("missing_source_rights", "FATWA_SOURCE_RIGHTS_AUTHORITY", None),
        ):
            with override_settings(**{field: value}):
                negative(key)
        actor = directory.identities["publisher"]
        directory.identities["publisher"] = replace(actor, active=False)
        negative("revoked_current_publisher")
        directory.identities["publisher"] = actor
        positive()
    assert _source(pins["case_id"]) == before
    return {
        "status": "PASS",
        "new_table_count": 0,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "exact_public_reference_and_version": True,
        "source_and_originals_unchanged": True,
        "restored_authority_grants": 0,
    }
