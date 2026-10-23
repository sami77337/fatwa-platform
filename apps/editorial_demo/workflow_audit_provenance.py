"""Pure, bounded provenance for consumers of an already-loaded synthetic window.

The caller's acknowledgement declares synthetic inputs; it proves neither their
origin nor source integrity. The read DTO exposes original row/reference slices,
not archive hashes or resolved edition identities. No missing identity, intake
timestamp, historical reference state or scholarly validity is inferred here.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import (
    ReviewBatchOption,
    ReviewWorklist,
    StoredReference,
    StoredReviewRow,
)

from .workflow_audit import AuditDataError, AuditEntry, build_audit_timeline


@dataclass(frozen=True, slots=True)
class AuditChronologyEntry:
    """An original timeline entry paired with its comparable UTC instant.

    ``entry.source.created_at`` and ``entry.timestamp`` retain the actual source
    timestamp, including offset and microseconds. UTC is a derived chronology
    value only, never an additional persisted event timestamp.
    """

    entry: AuditEntry
    instant_utc: datetime


@dataclass(frozen=True, slots=True)
class AuditProvenance:
    """Original objects plus explicit limits for future report/export consumers.

    A selected row may be outside the filtered page. ``worklist`` preserves that
    page and its filters without asserting that selection matches them. A batch
    is attached only to a selected row, as a provenance marker. Its creation is
    not row intake. References are current state and carry no historical date.
    Even an untruncated event window is never asserted to be complete history.
    """

    worklist: ReviewWorklist
    batch: ReviewBatchOption | None
    selected_row: StoredReviewRow | None
    references: tuple[StoredReference, ...]
    chronology: tuple[AuditChronologyEntry, ...]
    events_truncated: bool | None
    complete_history: Literal[False] = field(default=False, init=False)
    references_are_current_state: Literal[True] = field(default=True, init=False)
    batch_timestamp_is_row_intake_time: Literal[False] = field(default=False, init=False)
    event_limit: Literal[100] = field(default=100, init=False)
    synthetic_fixtures_declared: Literal[True] = field(default=True, init=False)
    synthetic_declaration_is_proof: Literal[False] = field(default=False, init=False)


def build_audit_provenance(
    stored: ReviewWorklist, *, synthetic_fixtures_only: bool = False,
) -> AuditProvenance:
    """Project one existing reader page and its selected <=100-event window.

    No reader, resolver, contract parser, filesystem or network is invoked. The
    established timeline builder owns selected batch/event identity validation
    and ordering, including equal instants and repeated local hours. Additional
    checks here only keep the retained window bounded and its collections frozen.
    They do not revalidate source slices against unavailable original bytes.
    """
    if synthetic_fixtures_only is not True:
        raise AuditDataError('synthetic_fixture_acknowledgement_required')
    timeline = build_audit_timeline(stored)
    if (not isinstance(stored.rows, tuple) or not isinstance(stored.batches, tuple)
            or type(stored.page_size) is not int or not 1 <= stored.page_size <= 50
            or len(stored.rows) > stored.page_size or len(stored.batches) > 101):
        raise AuditDataError('unbounded_or_mutable_worklist')
    for row in (*stored.rows, *((stored.row,) if stored.row is not None else ())):
        if (not isinstance(row, StoredReviewRow)
                or not isinstance(row.references, tuple) or not isinstance(row.events, tuple)
                or len(row.references) > c.MAX_REFERENCES_PER_ITEM or len(row.events) > 100
                or type(row.events_truncated) is not bool):
            raise AuditDataError('unbounded_or_mutable_row')
    # The authoritative timeline includes the selected batch exactly once. Do
    # not select by chronology position: a batch marker may follow an event.
    batch = next((entry.source for entry in timeline
                  if isinstance(entry.source, ReviewBatchOption)), None)
    return AuditProvenance(
        worklist=stored,
        batch=batch,
        selected_row=stored.row,
        references=stored.row.references if stored.row is not None else (),
        chronology=tuple(AuditChronologyEntry(
            entry, entry.source.created_at.astimezone(timezone.utc),
        ) for entry in timeline),
        events_truncated=stored.row.events_truncated if stored.row is not None else None,
    )
