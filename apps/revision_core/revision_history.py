"""Read-only history presentation using the existing immutable comparison service."""

import re
from dataclasses import dataclass

from apps.fatwa_drafts.domain import DraftRecord, Revision
from apps.fatwa_drafts.intake import IntakeItem, text

from .revision_comparison import compare_revisions

_ACTION_LABELS = {
    "synthetic_snapshot": "لقطة اصطناعية ثابتة",
    "synthetic_text_revision": "تغيير نص اصطناعي",
    "synthetic_reference_order": "تغيير ترتيب مراجع اصطناعية",
    "synthetic_notes_revision": "تغيير ملاحظات اصطناعية",
}


class HistoryDataError(ValueError):
    """The fixed fixture cannot form an unambiguous, bounded timeline."""


class InvalidRevisionId(ValueError):
    """A selection is absent or is not a canonical positive ASCII identifier."""


class UnknownRevisionId(LookupError):
    """A well-formed identity is absent from the available history."""


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    revision: Revision
    previous_number: int | None
    changed_fields: tuple[str, ...]
    references_added: int
    references_removed: int
    reference_positions_changed: int
    references_changed: bool

    @property
    def action_label(self) -> str:
        return _ACTION_LABELS.get(self.revision.action, "وسم عملية اصطناعية")

    @property
    def content_changed(self) -> bool:
        return bool(self.changed_fields) or self.references_changed


def build_history(record: DraftRecord) -> tuple[HistoryEntry, ...]:
    """Order snapshots by revision number; derive summaries without changing history.

    Numbers describe synthetic sequence, not real timestamps. Metadata labels do
    not trigger domain actions. Content validation/comparison is delegated unchanged.
    """
    if (not isinstance(record, DraftRecord) or not isinstance(record.intake, IntakeItem)
            or not isinstance(record.history, tuple)
            or not 1 <= len(record.history) <= 100):
        raise HistoryDataError("invalid_history")
    numbers = set()
    for revision in record.history:
        if (not isinstance(revision, Revision) or type(revision.number) is not int
                or not 1 <= revision.number <= 999999 or revision.number in numbers):
            raise HistoryDataError("invalid_or_duplicate_revision_identity")
        numbers.add(revision.number)
    entries = []
    previous = None
    try:
        for revision in sorted(record.history, key=lambda item: item.number):
            text(revision.action, "history.action", limit=100)
            text(revision.human_editor, "history.human_editor", limit=200)
            text(revision.editorial_note, "history.editorial_note", limit=2000)
            result = compare_revisions(previous or revision, revision)
            entries.append(HistoryEntry(
                revision, previous.number if previous is not None else None,
                tuple(field.label for field in result.fields if field.changed),
                sum(ref.kind == "added" for ref in result.after_references),
                sum(ref.kind == "removed" for ref in result.before_references),
                sum(ref.position_changed for ref in result.after_references),
                result.references_changed,
            ))
            previous = revision
    except (TypeError, ValueError) as exc:
        raise HistoryDataError("invalid_history_content") from exc
    return tuple(entries)


def select_revisions(
    entries: tuple[HistoryEntry, ...], before: object, after: object,
) -> tuple[Revision, Revision]:
    """Require two exact identities; never infer identity from a sequence offset."""
    for value in (before, after):
        if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]{0,5}", value) is None:
            raise InvalidRevisionId("invalid_or_missing_revision_identity")
    available = {str(entry.revision.number): entry.revision for entry in entries}
    try:
        return available[before], available[after]
    except KeyError as exc:
        raise UnknownRevisionId("unknown_revision_identity") from exc


@dataclass(frozen=True, slots=True)
class HistoryNavigation:
    """Original selected snapshot and its immediate revision-number neighbors."""

    selected: Revision
    previous: Revision | None
    next: Revision | None


def navigate_history(record: DraftRecord, selected: object) -> HistoryNavigation:
    """Select an exact identity and navigate the validated, bounded history.

    Order is by revision number, not tuple offset or timestamp. Gaps and unchanged
    content do not hide snapshots. A missing boundary neighbor is ``None``; invalid
    histories and selections retain the builder/selector exceptions unchanged.
    This read-only result carries no workflow authorization or state transition.
    """
    entries = build_history(record)
    revision, _ = select_revisions(entries, selected, selected)
    index = next(index for index, entry in enumerate(entries) if entry.revision is revision)
    return HistoryNavigation(
        revision,
        entries[index - 1].revision if index > 0 else None,
        entries[index + 1].revision if index + 1 < len(entries) else None,
    )
