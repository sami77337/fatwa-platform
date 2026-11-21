"""Independent current read/add grants for immutable operational internal notes."""

import uuid
from contextlib import contextmanager

from apps.case_organization import services as organization
from apps.casework import services as cases

from .boundary import scope


def access(case, guard):
    if not guard.note_feature:
        return {"read": False, "add": False}
    return {
        "read": guard.permit(case, "READ_INTERNAL_NOTES", "internal_notes"),
        "add": guard.permit(case, "ADD_INTERNAL_NOTE", "internal_notes"),
    }


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.note_feature:
        raise cases.CaseConflict("operational_notes_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_notes_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    cases._verify(case)
    return case


def _projection(case, guard, allowed, *, saved=False):
    history = organization._rows(case)
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "metadata_version": history[-1].version if history else 0,
        "command_id": str(uuid.uuid4()),
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "can_read": allowed["read"],
        "can_add": allowed["add"],
        "saved": saved,
        "history": [
            {
                "version": row.version,
                "note": row.note,
                "subject_id": row.subject_id,
                "created_at": row.created_at,
            }
            for row in reversed(history)
            if row.note
        ]
        if allowed["read"]
        else [],
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        allowed = access(case, guard)
        if not any(allowed.values()):
            raise cases.CaseConflict("operational_notes_denied")
        yield _projection(case, guard, allowed)


@contextmanager
def append(
    *,
    case_ref,
    note,
    command_id,
    expected_metadata_version,
    expected_revision,
    expected_evidence_version,
    **common,
):
    """Append one note; originals and metadata are copied, never accepted from the client.

    The command identity intentionally hashes only the caller's exact inputs. A
    later Mufti metadata revision cannot turn an identical retry into a new note.
    Rendering stays inside the transaction and the final current-access checks.
    """
    organization._text(note, 2000)
    command = cases._uuid(command_id)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if type(expected_metadata_version) is not int or not 0 <= expected_metadata_version < 256:
        raise cases.CaseConflict("organization_version_invalid")
    command_sha = organization._digest(
        {
            "action": "operational_internal_note",
            "note": note,
            "metadata_version": expected_metadata_version,
            "revision": expected_revision,
            "evidence_version": expected_evidence_version,
        }
    )
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        allowed = access(case, guard)
        if not allowed["add"]:
            raise cases.CaseConflict("operational_notes_denied")
        history = organization._rows(case)
        previous = history[-1] if history else None
        value = organization._values(
            list(previous.tags) if previous else [],
            list(previous.question_types) if previous else [],
            note,
        )
        _result, row = organization._append_locked(
            case=case,
            actor=guard.actor,
            provider_id=guard.provider_id,
            value=value,
            command=command,
            command_sha=command_sha,
            expected_metadata_version=expected_metadata_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )
        if row is not None:
            guard.account_for_note_append(row)
        yield _projection(case, guard, allowed, saved=True)
