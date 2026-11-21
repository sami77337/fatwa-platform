"""Nonempty service-created histories; restored trust is rebuilt, never serialized."""

import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_rights.tests import Authority as SourceAuthority

from . import public, services
from .models import PublicMediaAction, PublicMediaEdition, RecordingTranscript, TranscriptAction
from .test_support import FEATURES, TEXT, FixtureAuthority, FixtureMediaRights, MediaFixture, audio

MODELS = (RecordingTranscript, TranscriptAction, PublicMediaEdition, PublicMediaAction)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("pam_history_guard()",)
TRIGGERS = (
    "pam_transcript_guard",
    "pam_transcript_action_guard",
    "pam_edition_guard",
    "pam_media_action_guard",
)


def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _canonical(case_id):
    case = Case.objects.get(pk=case_id)
    return _digest(
        [
            list(Case.objects.filter(pk=case.pk).values()),
            case.source.original_question,
            case.source.question_sha256,
            list(case.evidence.order_by("version").values()),
            list(case.answers.order_by("revision").values()),
            list(case.decisions.order_by("pk").values()),
            list(case.events.order_by("sequence").values()),
        ]
    )


def _row_pins(case_id):
    queries = (
        RecordingTranscript.objects.filter(case_id=case_id),
        TranscriptAction.objects.filter(transcript__case_id=case_id),
        PublicMediaEdition.objects.filter(case_id=case_id),
        PublicMediaAction.objects.filter(edition__case_id=case_id),
    )
    result = {}
    for query in queries:
        rows = [[str(row["id"]), _digest(row)] for row in query.order_by("pk").values()]
        if not rows:
            raise AssertionError("recording recovery requires every history table nonempty")
        result[query.model._meta.db_table] = rows
    return result


class _Seed(MediaFixture, unittest.TestCase):
    pass


def populate():
    """Reuse only explicit synthetic fixture inputs; every mutation is a real service."""
    with override_settings(**FEATURES):
        fixture = _Seed()
        try:
            fixture.setUp()
            before = _canonical(fixture.receipt["case_id"])
            first = fixture.review(fixture.save())
            released = fixture.release(first)
            second = fixture.save(
                text="مسودة تصحيح محفوظة تحتاج إلى مراجعة المعنى",
                segments=[],
                change_kind="MEANING_REVIEW",
                expected_version=1,
            )
            if _canonical(fixture.receipt["case_id"]) != before:
                raise AssertionError("transcript fixture changed canonical source")
            return {
                "case": {
                    "case_id": fixture.receipt["case_id"],
                    "public_ref": fixture.receipt["public_ref"],
                    "canonical_sha256": before,
                },
                "publication": {
                    "id": str(fixture.publication.pk),
                    "sha256": fixture.publication.content_sha256,
                },
                "part": {"id": str(fixture.part.pk), "sha256": fixture.part.sha256},
                "transcripts": [
                    {key: row[key] for key in ("id", "number", "digest", "text", "reviewed")}
                    for row in (first, second)
                ],
                "media": {key: released[key] for key in ("id", "number", "digest")},
                "tables": _row_pins(fixture.receipt["case_id"]),
            }
        finally:
            fixture.doCleanups()


@contextmanager
def _fixture(pins):
    receipt = pins["case"]
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    rights = FixtureMediaRights(receipt["public_ref"])
    rights.pins.add(("ANSWER_MEDIA", pins["part"]["id"], pins["part"]["sha256"]))
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY": FixtureAuthority(receipt["public_ref"]),
            "FATWA_RESEARCH_WORKSPACE_RIGHTS": rights,
            "FATWA_SOURCE_RIGHTS_AUTHORITY": SourceAuthority(receipt["public_ref"]),
            "FATWA_LIBRARY_PREVIEW_POLICY": PreviewPolicy(
                (PublicationGrant(pins["publication"]["id"], pins["publication"]["sha256"]),),
                (),
                timezone.now() + timedelta(minutes=30),
                True,
            ),
        }
    ):
        yield dict(
            case_id=receipt["case_id"],
            subject_id="editor",
            provider=directory,
            synthetic_fixtures_only=True,
        )


def _verify_available(pins, common):
    for expected in pins["transcripts"]:
        with services.transcript_projection(**common, transcript_id=expected["id"]) as row:
            if any(row[key] != value for key, value in expected.items()) or row["raw"] != audio():
                raise AssertionError("restored exact recording or transcript changed")
    with services.search_projection(**common) as result:
        if (
            len(result["rows"]) != 1
            or result["rows"][0]["pin"]["transcript_id"] != pins["transcripts"][0]["id"]
        ):
            raise AssertionError("restored unreviewed draft inherited searchable segment rights")
    with public.recording_projection(pins["media"]["id"]) as result:
        if result["file"]["raw"] != audio() or result["recording"]["text"] != TEXT:
            raise AssertionError("restored public exact recording changed")
        if result["recording"]["segments"][0]["start_ms"] != 1000:
            raise AssertionError("restored documented segment changed")


def _deny_private(pins, common):
    current = {**common, "provider": getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)}
    try:
        with services.transcript_projection(**current, transcript_id=pins["transcripts"][0]["id"]):
            pass
    except cases.CaseConflict:
        return 1
    raise AssertionError("restored transcript survived missing current trust")


def _deny_public(pins):
    try:
        with public.recording_projection(pins["media"]["id"]):
            pass
    except preview.PreviewUnavailable:
        return 1
    raise AssertionError("restored media inherited a durable public permission")


def verify_restored(pins):
    receipt = pins["case"]
    before = _row_pins(receipt["case_id"])
    if before != pins["tables"] or _canonical(receipt["case_id"]) != receipt["canonical_sha256"]:
        raise AssertionError("restored recording rows or original case pins changed")
    denied = {}
    with _fixture(pins) as common:
        _verify_available(pins, common)
        for label, name in (
            ("missing_authority", "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY"),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER"),
            ("missing_media_rights", "FATWA_RESEARCH_WORKSPACE_RIGHTS"),
        ):
            with override_settings(**{name: None}):
                denied[label] = _deny_private(pins, common) + _deny_public(pins)
        directory = common["provider"]
        actor = directory.identities["editor"]
        try:
            directory.identities["editor"] = replace(actor, active=False)
            denied["revoked_current_reader"] = _deny_private(pins, common) + _deny_public(pins)
        finally:
            directory.identities["editor"] = actor
        actor = directory.identities["publisher"]
        try:
            directory.identities["publisher"] = replace(actor, active=False)
            denied["revoked_public_release_actor"] = _deny_public(pins)
        finally:
            directory.identities["publisher"] = actor
        _verify_available(pins, common)
    if (
        _row_pins(receipt["case_id"]) != before
        or _canonical(receipt["case_id"]) != receipt["canonical_sha256"]
    ):
        raise AssertionError("restored recording verification mutated rows")
    return {
        "table_count": 4,
        "case_count": 1,
        "transcript_count": 2,
        "transcript_action_count": 1,
        "media_edition_count": 1,
        "media_action_count": 2,
        "original_audio_sha256": pins["part"]["sha256"],
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
    }
