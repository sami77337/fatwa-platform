"""Immutable snapshots and isolated synthetic staging, with no persistence adapter."""

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock
from typing import NotRequired, TypedDict, Unpack

from .intake import IntakeItem, ReferenceLink, ValidationError, parse_intake, text


class State(StrEnum):
    RECEIVED = "received"
    PREPARATION = "draft_preparation"
    NEEDS_REVISION = "needs_revision"
    READY = "ready_for_future_review"


class RevisionConflict(ValidationError):
    pass


@dataclass(frozen=True, slots=True)
class Revision:
    number: int
    action: str
    human_editor: str
    editorial_note: str
    state: State
    title: str
    answer: str
    reference_links: tuple[ReferenceLink, ...]
    reviewer_notes: str


@dataclass(frozen=True, slots=True)
class DraftRecord:
    intake: IntakeItem
    history: tuple[Revision, ...]

    @property
    def current(self) -> Revision:
        return self.history[-1]

    @property
    def unpublished(self) -> bool:
        return True


def _human(editor: str, note: str) -> None:
    # These are staff-supplied attribution labels, not authentication or role grants.
    text(editor, "human_editor", limit=200)
    text(note, "editorial_note", limit=2000)


def create_draft(item: IntakeItem, *, human_editor: str, editorial_note: str) -> DraftRecord:
    _human(human_editor, editorial_note)
    if not isinstance(item, IntakeItem):
        raise ValidationError("intake: invalid_item")
    return DraftRecord(
        item,
        (
            Revision(
                1,
                "received",
                human_editor,
                editorial_note,
                State.RECEIVED,
                "",
                "",
                item.reference_links,
                "",
            ),
        ),
    )


def _check(record: DraftRecord, expected_revision: int) -> None:
    if type(expected_revision) is not int or record.current.number != expected_revision:
        raise RevisionConflict("revision: conflict")


def edit_draft(
    record: DraftRecord,
    *,
    expected_revision: int,
    human_editor: str,
    editorial_note: str,
    title: str,
    answer: str,
    reviewer_notes: str,
    reference_links: tuple[ReferenceLink, ...] | None = None,
) -> DraftRecord:
    """Full human replacement of editable text; original intake remains immutable."""
    _check(record, expected_revision)
    _human(human_editor, editorial_note)
    if record.current.state not in (State.PREPARATION, State.NEEDS_REVISION):
        raise ValidationError("state: edit_requires_preparation_or_revision")
    text(title, "title", required=False, limit=500)
    text(answer, "answer", required=False, limit=100000)
    text(reviewer_notes, "reviewer_notes", required=False)
    refs = record.current.reference_links if reference_links is None else reference_links
    # Reuse intake validation, preserving every source field exactly as supplied.
    replace(record.intake, reference_links=refs)
    revision = Revision(
        record.current.number + 1,
        "human_edit",
        human_editor,
        editorial_note,
        record.current.state,
        title,
        answer,
        refs,
        reviewer_notes,
    )
    return replace(record, history=(*record.history, revision))


_ALLOWED = {
    State.RECEIVED: {State.PREPARATION},
    State.PREPARATION: {State.NEEDS_REVISION, State.READY},
    State.NEEDS_REVISION: {State.PREPARATION},
    State.READY: {State.NEEDS_REVISION},
}


def transition(
    record: DraftRecord,
    target: str,
    *,
    expected_revision: int,
    human_editor: str,
    editorial_note: str,
) -> DraftRecord:
    _check(record, expected_revision)
    _human(human_editor, editorial_note)
    try:
        state = State(target)
    except (ValueError, TypeError) as exc:
        raise ValidationError("state: prohibited_transition") from exc
    if state not in _ALLOWED[record.current.state]:
        raise ValidationError("state: prohibited_transition")
    if state == State.READY:
        text(record.current.title, "title", limit=500)
        text(record.current.answer, "human_answer", limit=100000)
    revision = replace(
        record.current,
        number=record.current.number + 1,
        action="transition",
        state=state,
        human_editor=human_editor,
        editorial_note=editorial_note,
    )
    return replace(record, history=(*record.history, revision))


class HumanMetadata(TypedDict):
    human_editor: str
    editorial_note: str


class RevisionCommand(HumanMetadata):
    expected_revision: int


class EditCommand(RevisionCommand):
    title: str
    answer: str
    reviewer_notes: str
    reference_links: NotRequired[tuple[ReferenceLink, ...] | None]


class SyntheticStage:
    """Process-local test-fixture store only. No loading/saving production records.

    The explicit flag is an integration guard, not a claim to detect sensitive data.
    A lock makes revision comparisons and replacements atomic within this instance.
    """

    def __init__(self, *, synthetic_fixtures_only: bool = False):
        if synthetic_fixtures_only is not True:
            raise ValidationError("stage: synthetic_fixture_acknowledgement_required")
        self._records: dict[str, DraftRecord] = {}
        self._lock = RLock()

    def ingest(
        self, payload: bytes, *, human_editor: str, editorial_note: str
    ) -> tuple[DraftRecord, ...]:
        items = parse_intake(payload)
        records = tuple(
            create_draft(item, human_editor=human_editor, editorial_note=editorial_note)
            for item in items
        )
        with self._lock:
            if any(item.external_id in self._records for item in items):
                raise ValidationError("external_id: duplicate_id")
            self._records.update((r.intake.external_id, r) for r in records)
        return records

    def get(self, external_id: str) -> DraftRecord:
        with self._lock:
            try:
                return self._records[external_id]
            except KeyError as exc:
                raise ValidationError("external_id: not_found") from exc

    def edit(self, external_id: str, **changes: Unpack[EditCommand]) -> DraftRecord:
        with self._lock:
            record = edit_draft(self.get(external_id), **changes)
            self._records[external_id] = record
            return record

    def move(
        self, external_id: str, target: str, **changes: Unpack[RevisionCommand]
    ) -> DraftRecord:
        with self._lock:
            record = transition(self.get(external_id), target, **changes)
            self._records[external_id] = record
            return record

    def preview(self, *, include_synthetic_content: bool = False) -> bytes:
        """Read-only deterministic report. Default excludes IDs, URLs and all free text."""
        with self._lock:
            rows = []
            for key in sorted(self._records):
                record = self._records[key]
                current = record.current
                row: dict[str, object] = {
                    "state": current.state.value,
                    "revision": current.number,
                    "unpublished": True,
                    "reference_count": len(current.reference_links),
                    "reference_status": (
                        "unverified_editorial_pointers"
                        if current.reference_links
                        else "missing_manual_references"
                    ),
                    "title_missing": not bool(current.title.strip()),
                    "human_answer_missing": not bool(current.answer.strip()),
                }
                if include_synthetic_content:
                    from dataclasses import asdict

                    row["synthetic_record"] = asdict(record)
                rows.append(row)
            return json.dumps(
                {"kind": "SYNTHETIC_UNPUBLISHED_DRAFT_PREVIEW", "items": rows},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
