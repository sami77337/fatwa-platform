"""Restored public references require rebuilt current trust; no permissions persist."""

import unittest
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as audio
from apps.answer_media.models import AnswerPart
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.public_answer_media.boundaries import core_state
from apps.public_answer_media.recovery_support import _canonical, _digest
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_rights.tests import Authority as SourceAuthority

from . import services
from .test_support import FEATURES, FixtureAuthority, ReaderFixture

# Device bookmarks are not server rows. The reused canonical publication and
# original audio remain in their existing recovery inventories, without new credit.
TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


class _Seed(ReaderFixture, unittest.TestCase):
    pass


def _source_pins(case_id):
    return (_canonical(case_id), _digest(core_state(case_id)))


def populate():
    with override_settings(**FEATURES):
        seed = _Seed()
        try:
            seed.setUp()
            with services.reader_projection(seed.publication.pk) as result:
                if tuple(result["actions"]) != services.ACTIONS:
                    raise AssertionError("synthetic exact tool fixture is incomplete")
                copied = services.text_copy(result)
            return {
                "case_id": seed.receipt["case_id"],
                "case_ref": seed.receipt["public_ref"],
                "publication_id": str(seed.publication.pk),
                "publication_sha256": seed.publication.content_sha256,
                "part_id": str(seed.part.pk),
                "part_sha256": seed.part.sha256,
                "download_sha256": sha256(copied).hexdigest(),
                "source_pins": list(_source_pins(seed.receipt["case_id"])),
            }
        finally:
            seed.doCleanups()


def _positive(pins):
    with services.reader_projection(pins["publication_id"]) as result:
        if tuple(result["actions"]) != services.ACTIONS:
            raise AssertionError("restored current capabilities changed")
        if (
            result["descriptor"]["content_sha256"] != pins["publication_sha256"]
            or sha256(services.text_copy(result)).hexdigest() != pins["download_sha256"]
        ):
            raise AssertionError("restored exact public text copy changed")


def _denied(pins, action="DOWNLOAD_TEXT"):
    try:
        with services.reader_projection(pins["publication_id"], action=action):
            pass
    except preview.PreviewUnavailable:
        return 1
    raise AssertionError("restored public tool inherited missing current permission")


def verify_restored(pins):
    before = _source_pins(pins["case_id"])
    if list(before) != pins["source_pins"]:
        raise AssertionError("restored source rows changed")
    part = AnswerPart.objects.get(pk=pins["part_id"])
    raw_before = audio.raw_for_part(part)
    if sha256(raw_before).hexdigest() != pins["part_sha256"]:
        raise AssertionError("restored original audio changed")
    directory = bind_identity_snapshot(Directory([pins["case_ref"]]))
    row = PublicationEdition.objects.get(pk=pins["publication_id"])
    authority = FixtureAuthority(row, directory.provider_id)
    selected = PreviewPolicy(
        (PublicationGrant(str(row.pk), pins["publication_sha256"]),),
        (),
        timezone.now() + timedelta(minutes=20),
        True,
    )
    denied = {}
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLIC_READER_TOOLS_AUTHORITY": authority,
            "FATWA_SOURCE_RIGHTS_AUTHORITY": SourceAuthority(pins["case_ref"]),
            "FATWA_LIBRARY_PREVIEW_POLICY": selected,
        }
    ):
        _positive(pins)
        for label, name in (
            ("missing_tool_authority", "FATWA_PUBLIC_READER_TOOLS_AUTHORITY"),
            ("missing_current_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER"),
            ("missing_publication_grant", "FATWA_LIBRARY_PREVIEW_POLICY"),
        ):
            with override_settings(**{name: None}):
                denied[label] = _denied(pins)
        actor = directory.identities["publisher"]
        try:
            directory.identities["publisher"] = replace(actor, active=False)
            denied["revoked_current_authorizer"] = _denied(pins)
        finally:
            directory.identities["publisher"] = actor
        for action in services.ACTIONS:
            grant = authority.grants.pop(action)
            try:
                denied["missing_" + action.lower()] = _denied(pins, action)
            finally:
                authority.grants[action] = grant
        _positive(pins)
    if _source_pins(pins["case_id"]) != before or audio.raw_for_part(part) != raw_before:
        raise AssertionError("tool recovery verification mutated source rows or original bytes")
    return {
        "table_count": 0,
        "reused_publication_count": 1,
        "device_bookmarks_restored": 0,
        "action_count": len(services.ACTIONS),
        "download_sha256": pins["download_sha256"],
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
        "source_rows_and_original_bytes_unchanged": True,
    }
