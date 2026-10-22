"""Pure presentation of existing Wave7 read DTOs; no snapshots or persistence."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from apps.intake_workflow.review import (
    ReviewBatchOption, ReviewWorklist, StoredReviewEvent, StoredReviewRow,
)


class AuditDataError(ValueError):
    """The read result cannot identify an unambiguous bounded timeline."""


@dataclass(frozen=True, slots=True)
class AuditEntry:
    source: ReviewBatchOption | StoredReviewEvent

    @property
    def kind(self) -> str:
        return 'review' if isinstance(self.source, StoredReviewEvent) else 'batch'

    @property
    def timestamp(self) -> str:
        return self.source.created_at.isoformat()

    @property
    def anchor(self) -> str:
        return ('event-' if self.kind == 'review' else 'batch-') + str(self.source.id)


def _dated_identity(source: ReviewBatchOption | StoredReviewEvent) -> None:
    if (type(source.id) is not UUID or not isinstance(source.created_at, datetime)
            or source.created_at.utcoffset() is None):
        raise AuditDataError('invalid_dated_identity')


def build_audit_timeline(stored: ReviewWorklist) -> tuple[AuditEntry, ...]:
    """Order actual batch creation and the reader's latest <=100 review events.

    Batch creation is a provenance marker, not a new persisted event or a row's
    intake timestamp. References are current state and have no date in this DTO.
    Text, reference order, identities and source objects remain untouched.
    """
    if not isinstance(stored, ReviewWorklist):
        raise AuditDataError('invalid_worklist')
    if stored.row is None:
        return ()
    row = stored.row
    if (not isinstance(row, StoredReviewRow) or type(row.id) is not UUID
            or type(stored.batch_id) is not UUID or row.batch_id != stored.batch_id
            or not isinstance(row.events, tuple) or len(row.events) > 100):
        raise AuditDataError('invalid_selected_row')
    batches = tuple(batch for batch in stored.batches if batch.id == stored.batch_id)
    if len(batches) != 1 or not isinstance(batches[0], ReviewBatchOption):
        raise AuditDataError('missing_or_duplicate_batch')
    _dated_identity(batches[0])
    identities, operations = set(), set()
    for event in row.events:
        if not isinstance(event, StoredReviewEvent):
            raise AuditDataError('invalid_review_event')
        _dated_identity(event)
        if (type(event.operation_id) is not UUID or event.id in identities
                or event.operation_id in operations):
            raise AuditDataError('duplicate_or_invalid_event_identity')
        identities.add(event.id)
        operations.add(event.operation_id)
    sources = (batches[0], *row.events)
    return tuple(AuditEntry(source) for source in sorted(sources, key=lambda source: (
        # A repeated local hour can compare by wall time when tzinfo is shared.
        # Compare instants in UTC without changing the source or displayed time.
        source.created_at.astimezone(timezone.utc), isinstance(source, StoredReviewEvent), source.id,
    )))
