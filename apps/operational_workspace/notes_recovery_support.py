"""Exact immutable notes reopen under fresh explicit operational read grants."""

import unittest
from dataclasses import replace

from django.db import connection
from django.test import override_settings

from apps.casework import services as cases

from . import notes
from .boundary import digest
from .notes_test_support import NOTE_FEATURES, NoteFixture, grant_notes
from .recovery_support import current_trust, row_pins

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def read(pins, common):
    with notes.projection(case_ref=pins["case_ref"], **common) as result:
        assert result["role"] == "ORGANIZER"
        assert result["can_read"] is True and result["can_add"] is True
        assert len(result["history"]) == 2
        return {
            "history_digest": digest(result["history"]),
            "metadata_version": result["metadata_version"],
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
        }


def populate():
    class Fixture(NoteFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    with override_settings(**NOTE_FEATURES):
        try:
            fixture.setUp()
            fixture.append_note()
            assert fixture.immutable_state() == fixture.note_originals
            pins = {"cases": fixture.receipts, "case_ref": fixture.target["public_ref"]}
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
    with (
        current_trust(pins["cases"]) as (common, authority),
        override_settings(FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED=True),
    ):
        grant_notes(authority, pins["cases"])
        assert read(pins, common) == pins["expected"]

        def refusal(kind):
            try:
                with notes.projection(case_ref=pins["case_ref"], **common):
                    pass
            except cases.CaseConflict:
                denied[kind] = denied.get(kind, 0) + 1
            else:
                raise AssertionError("restored note history supplied missing current permission")

        for kind, setting, value in (
            ("disabled_note_feature", "FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED", False),
            ("disabled_metadata", "FATWA_CASE_ORGANIZATION_ENABLED", False),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
        ):
            with override_settings(**{setting: value}):
                refusal(kind)
        directory = common["provider"]
        original = directory.identities["operator"]
        directory.identities["operator"] = replace(original, active=False)
        refusal("revoked_current_identity")
        directory.identities["operator"] = original
        grants = set(authority.grants)
        authority.revoke(action="READ_CASE", case_ref=pins["case_ref"])
        refusal("revoked_case_read")
        authority.grants = set(grants)
        authority.revoke(action="READ_INTERNAL_NOTES")
        authority.revoke(action="ADD_INTERNAL_NOTE")
        refusal("revoked_note_actions")
        authority.grants = set(grants)
        # The flag below describes this actual positive read, after every denial.
        assert read(pins, common) == pins["expected"]
    assert row_pins(pins["cases"]) == before == pins["tables"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "note_count": 2,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_source_and_metadata_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
