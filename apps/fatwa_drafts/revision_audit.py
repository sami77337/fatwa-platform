"""Pure read-only audit of explicitly acknowledged synthetic draft snapshots."""

from dataclasses import dataclass

from apps.editorial_demo.revision_history import HistoryDataError, HistoryEntry, build_history

from .domain import DraftRecord, Revision, State

_METADATA_FIELDS = ("action", "human_editor", "editorial_note", "state")


@dataclass(frozen=True, slots=True)
class RevisionAuditEntry:
    """Retain original snapshots and existing content-change summaries verbatim.

    Human editor values are supplied attribution labels, not authenticated actors.
    Metadata changes compare adjacent numbered snapshots without interpreting actions.
    """

    history_entry: HistoryEntry
    previous_revision: Revision | None
    changed_metadata: tuple[str, ...]

    @property
    def revision(self) -> Revision:
        return self.history_entry.revision

    @property
    def observed_state_change(self) -> tuple[State, State] | None:
        """Report differing stored labels; never execute or authorize a transition."""
        previous = self.previous_revision
        if previous is None or previous.state == self.revision.state:
            return None
        return previous.state, self.revision.state


@dataclass(frozen=True, slots=True)
class RevisionAuditSummary:
    """Keep all intake/source data and revision identities in their original objects."""

    record: DraftRecord
    entries: tuple[RevisionAuditEntry, ...]


def build_revision_audit(
    record: DraftRecord, *, synthetic_fixtures_only: bool = False
) -> RevisionAuditSummary:
    """Summarize immutable synthetic snapshots without writes, timestamps or actors.

    The literal-True acknowledgement is an integration guard, not evidence that
    the supplied record is synthetic or that its source identities are verified.
    Revision numbers order observations and need not be consecutive; the first
    snapshot has no inferred predecessor or metadata changes. State differences
    do not establish whether a workflow transition occurred or was permissible.

    Existing history validation and bounded text/reference comparison are reused
    unchanged, including their 100-snapshot and 10,000-character text limits.
    No content is trimmed, normalized, rewritten or assessed for scholarly merit.
    """
    if synthetic_fixtures_only is not True:
        raise HistoryDataError("audit: synthetic_fixture_acknowledgement_required")
    history = build_history(record)
    if any(not isinstance(entry.revision.state, State) for entry in history):
        raise HistoryDataError("invalid_history_state")
    entries: list[RevisionAuditEntry] = []
    previous: Revision | None = None
    for entry in history:
        changed_metadata = (
            tuple(
                field
                for field in _METADATA_FIELDS
                if getattr(previous, field) != getattr(entry.revision, field)
            )
            if previous is not None
            else ()
        )
        entries.append(RevisionAuditEntry(entry, previous, changed_metadata))
        previous = entry.revision
    return RevisionAuditSummary(record, tuple(entries))
