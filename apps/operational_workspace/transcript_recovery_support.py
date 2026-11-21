"""Recovered editorial history never supplies current roles, read rights or meaning approval."""

import unittest
from contextlib import contextmanager
from dataclasses import replace

from django.db import connection
from django.test import override_settings

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases

from . import transcripts
from .boundary import digest
from .recovery_support import row_pins
from .test_support import Directory, Profiles
from .transcript_test_support import (
    TRANSCRIPT_FEATURES,
    TranscriptAuthority,
    TranscriptDomainAuthority,
    TranscriptFixture,
    TranscriptMediaRights,
    grant_transcripts,
)

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def read(pins, common):
    with transcripts.projection(case_ref=pins["case_ref"], **common) as result:
        assert result["role"] == "ORGANIZER"
        assert len(result["parts"]) == 1 and len(result["transcripts"]) == 2
        assert result["transcripts"][0]["history"][0]["action"] == "REVIEW"
        assert [row["action"] for row in result["transcripts"][1]["history"]] == [
            "APPROVE_MEANING",
            "WITHDRAW",
        ]
        assert result["transcripts"][1]["history"][0]["subject_id"] == "mufti"
        return {
            "parts": digest(result["parts"]),
            "transcripts": digest(result["transcripts"]),
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
        }


@contextmanager
def current_trust(pins):
    directory = Directory(
        [row["public_ref"] for key, row in pins["cases"].items() if key != "unscoped"]
    )
    authority, domain = TranscriptAuthority(pins["cases"]), TranscriptDomainAuthority()
    rights = TranscriptMediaRights(authority.until)
    part = AnswerPart.objects.get(pk=pins["part_id"])
    grant_transcripts(authority, domain, rights, pins["cases"]["transcripts"], part)
    with override_settings(
        **{
            **TRANSCRIPT_FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY": domain,
            "FATWA_RESEARCH_WORKSPACE_RIGHTS": rights,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": Profiles(),
        }
    ):
        yield (
            dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True),
            authority,
            domain,
            rights,
        )


def populate():
    class Fixture(TranscriptFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**TRANSCRIPT_FEATURES):
        try:
            fixture.setUp()
            fixture.save_transcript()
            fixture.review_transcript()
            fixture.save_transcript(
                change_kind="MEANING_REVIEW", text="نسخة اصطناعية تحتاج مراجعة المعنى"
            )
            fixture.review_transcript(subject="mufti", action="APPROVE_MEANING")
            fixture.review_transcript(action="WITHDRAW")
            assert fixture.immutable_transcript_sources() == fixture.transcript_originals
            pins = {
                "cases": fixture.receipts,
                "case_ref": fixture.target["public_ref"],
                "part_id": str(fixture.part.pk),
                "part_sha256": fixture.part.sha256,
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
    with current_trust(pins) as (common, authority, domain, rights):
        assert read(pins, common) == pins["expected"]

        def refusal(kind, *, audio=False):
            try:
                reader = transcripts.audio_projection if audio else transcripts.projection
                values = (
                    {"part_id": pins["part_id"], "part_sha256": pins["part_sha256"]}
                    if audio
                    else {}
                )
                with reader(case_ref=pins["case_ref"], **common, **values):
                    pass
            except cases.CaseConflict:
                denied[kind] = 1
            else:
                raise AssertionError("restored transcript inferred current permissions")

        for kind, name, value in (
            ("disabled_transcript_editor", "FATWA_OPERATIONAL_TRANSCRIPTS_ENABLED", False),
            ("disabled_recording", "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", False),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_operational_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_transcript_authority", "FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY", None),
            ("missing_media_rights", "FATWA_RESEARCH_WORKSPACE_RIGHTS", None),
        ):
            with override_settings(**{name: value}):
                refusal(kind)
        directory = common["provider"]
        actor = directory.identities["operator"]
        directory.identities["operator"] = replace(actor, active=False)
        refusal("revoked_current_editor")
        directory.identities["operator"] = actor
        sections, rules = set(authority.grants), set(authority.transcript_rules)
        for action in ("READ_CASE", "READ_TRANSCRIPT_EDITOR"):
            authority.revoke(action=action, case_ref=pins["case_ref"])
            refusal("revoked_" + action.lower())
            authority.grants = set(sections)
        authority.revoke(action="READ_RECORDING_TRANSCRIPT")
        with transcripts.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["parts"] == result["transcripts"] == []
        denied["revoked_exact_transcript_read"] = 1
        authority.transcript_rules = set(rules)
        authority.revoke(action="READ_RECORDING_AUDIO")
        refusal("revoked_exact_audio_read", audio=True)
        authority.transcript_rules = set(rules)
        domain.denied.add(("operator", "READ_TRANSCRIPT"))
        with transcripts.projection(case_ref=pins["case_ref"], **common) as result:
            assert result["parts"] == result["transcripts"] == []
        denied["revoked_domain_transcript_read"] = 1
        domain.denied.clear()
        rights.denied.add("operator")
        refusal("revoked_current_media_right")
        rights.denied.clear()
        assert read(pins, common) == pins["expected"]
        with transcripts.audio_projection(
            case_ref=pins["case_ref"],
            part_id=pins["part_id"],
            part_sha256=pins["part_sha256"],
            **common,
        ) as result:
            assert result["raw"] and result["media_type"] == "audio/wav"
    assert row_pins(pins["cases"]) == before == pins["tables"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "transcript_version_count": 2,
        "meaning_approver_is_actual_mufti": True,
        "preserved_editorial_review_meaning_review_and_withdrawal": True,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_sources_and_immutable_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
