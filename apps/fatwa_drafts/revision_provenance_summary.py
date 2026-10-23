"""Pure reviewer aggregates over explicitly acknowledged synthetic revision audits."""

from dataclasses import dataclass

from .domain import DraftRecord, State
from .revision_audit import RevisionAuditEntry, RevisionAuditSummary, build_revision_audit


@dataclass(frozen=True, slots=True)
class AttributionSummary:
    """Exact supplied label and its snapshots; this does not identify an actor."""

    label: str
    entries: tuple[RevisionAuditEntry, ...]

    @property
    def snapshot_count(self) -> int:
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class ObservedStateChangeSummary:
    """Repeated stored state pairs, with original audit entries for inspection.

    The pair establishes neither a workflow event nor its permissibility.
    """

    before: State
    after: State
    entries: tuple[RevisionAuditEntry, ...]

    @property
    def observation_count(self) -> int:
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class RevisionProvenanceSummary:
    """Count changes without losing the original audit, snapshots or source pointers.

    The four change counts partition comparisons, excluding the initial snapshot.
    Metadata frequencies count comparisons per field (including zero frequencies),
    so their sum may exceed the number of comparisons. Attribution totals include
    the initial snapshot and count stored labels, not edits, people or approvals.
    """

    audit: RevisionAuditSummary
    content_only_count: int
    metadata_only_count: int
    content_and_metadata_count: int
    unchanged_count: int
    metadata_change_frequencies: tuple[tuple[str, int], ...]
    attributions: tuple[AttributionSummary, ...]
    observed_state_changes: tuple[ObservedStateChangeSummary, ...]

    @property
    def snapshot_count(self) -> int:
        return len(self.audit.entries)

    @property
    def comparison_count(self) -> int:
        return self.snapshot_count - 1


def build_revision_provenance_summary(
    record: DraftRecord, *, synthetic_fixtures_only: bool = False
) -> RevisionProvenanceSummary:
    """Aggregate existing audit observations without I/O or new validation rules.

    The literal-True acknowledgement is delegated to the auditor; it does not
    verify synthetic origin, source identity or approval. Existing history and
    comparison bounds remain authoritative. Revision numbers only order supplied
    observations; gaps establish no intervening events, elapsed time or states.

    Metadata frequencies use action/editor/note/state order. Label and state-pair
    groups use first observed revision-number order, with entries in that same
    order. Every group retains the auditor's entries by identity, without text
    normalization, authenticated attribution or interpretation of action labels.
    """
    audit = build_revision_audit(record, synthetic_fixtures_only=synthetic_fixtures_only)
    comparisons = audit.entries[1:]
    content_only = metadata_only = both = unchanged = 0
    for entry in comparisons:
        content_changed = entry.history_entry.content_changed
        metadata_changed = bool(entry.changed_metadata)
        if content_changed and metadata_changed:
            both += 1
        elif content_changed:
            content_only += 1
        elif metadata_changed:
            metadata_only += 1
        else:
            unchanged += 1

    labels: list[str] = []
    state_pairs: list[tuple[State, State]] = []
    for entry in audit.entries:
        if entry.revision.human_editor not in labels:
            labels.append(entry.revision.human_editor)
        pair = entry.observed_state_change
        if pair is not None and pair not in state_pairs:
            state_pairs.append(pair)

    return RevisionProvenanceSummary(
        audit=audit,
        content_only_count=content_only,
        metadata_only_count=metadata_only,
        content_and_metadata_count=both,
        unchanged_count=unchanged,
        metadata_change_frequencies=tuple(
            (field, sum(field in entry.changed_metadata for entry in comparisons))
            for field in ("action", "human_editor", "editorial_note", "state")
        ),
        attributions=tuple(
            AttributionSummary(
                label, tuple(entry for entry in audit.entries if entry.revision.human_editor == label)
            )
            for label in labels
        ),
        observed_state_changes=tuple(
            ObservedStateChangeSummary(
                before, after,
                tuple(entry for entry in comparisons if entry.observed_state_change == (before, after)),
            )
            for before, after in state_pairs
        ),
    )
