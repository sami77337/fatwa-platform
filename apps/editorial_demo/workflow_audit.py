"""Pure presentation of existing Wave7 read DTOs; no snapshots or persistence."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import (
    ReviewBatchOption, ReviewWorklist, StoredReference, StoredReviewEvent, StoredReviewRow,
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


MAX_AUDIT_JSON_BYTES = 4 * 1024 * 1024


def _audit_text(value: object, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise AuditDataError('invalid_audit_export_dto')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise AuditDataError('invalid_audit_export_dto') from None


def _validate_audit_export(stored: ReviewWorklist) -> None:
    """Check the fixed v1 DTO shape before asdict can copy arbitrary values.

    Dataclass annotations are not runtime checks. In particular, bool is an int
    subclass and asdict includes extra fields on dataclass subclasses. Reject
    malformed reader results without coercing or rewriting any source values.
    """
    if (type(stored) is not ReviewWorklist or type(stored.rows) is not tuple
            or type(stored.batches) is not tuple
            or stored.batch_id is not None and type(stored.batch_id) is not UUID
            or any(type(value) is not int for value in (
                stored.total_count, stored.matched_count, stored.page,
                stored.page_count, stored.page_size))):
        raise AuditDataError('invalid_audit_export_dto')
    if (not 1 <= stored.page_size <= 50 or len(stored.rows) > stored.page_size
            or len(stored.batches) > 101):
        raise AuditDataError('unbounded_worklist')
    for value in (stored.q, stored.mode, stored.intake_status, stored.review_status):
        _audit_text(value)
    for batch in stored.batches:
        if type(batch) is not ReviewBatchOption:
            raise AuditDataError('invalid_audit_export_dto')
        _dated_identity(batch)
    for row in (*stored.rows, *((stored.row,) if stored.row is not None else ())):
        if (type(row) is not StoredReviewRow or type(row.id) is not UUID
                or type(row.batch_id) is not UUID
                or any(type(value) is not int for value in (
                    row.row_ordinal, row.source_byte_start, row.source_byte_end))
                or type(row.events_truncated) is not bool
                or type(row.references) is not tuple or type(row.events) is not tuple):
            raise AuditDataError('invalid_audit_export_dto')
        if len(row.references) > c.MAX_REFERENCES_PER_ITEM or len(row.events) > 100:
            raise AuditDataError('unbounded_row')
        for value in (row.external_id, row.question, row.prepared_clip_url):
            _audit_text(value, nullable=True)
        for value in (row.original_row, row.intake_status, row.review_status):
            _audit_text(value)
        for reference in row.references:
            if (type(reference) is not StoredReference or type(reference.id) is not UUID
                    or type(reference.source_byte_start) is not int
                    or type(reference.source_byte_end) is not int):
                raise AuditDataError('invalid_audit_export_dto')
            for value in (reference.original_pointer, reference.reference_status,
                          reference.citation_text):
                _audit_text(value)
        for event in row.events:
            if type(event) is not StoredReviewEvent or type(event.operation_id) is not UUID:
                raise AuditDataError('invalid_audit_export_dto')
            _dated_identity(event)
            for value in (event.action, event.from_status, event.to_status, event.reason):
                _audit_text(value)


def serialize_audit_json(stored: ReviewWorklist) -> bytes:
    """Export one guarded reader page, never fetch additional rows or history.

    References are current state, batch creation is only a provenance marker,
    and the selected row's latest event window is not complete history.
    Reject oversized output rather than truncating source text or identities.
    """
    import json
    from dataclasses import asdict

    _validate_audit_export(stored)
    timeline = build_audit_timeline(stored)

    def scalar(value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError('unsupported_audit_value')

    payload = {
        'schema': 'wave7.audit.v1',
        'scope': c.SYNTHETIC_SCOPE,
        'source_config_id': c.SOURCE_CONFIG_ID,
        'contract_version': c.CONTRACT_VERSION,
        'complete_history': False,
        'references_are_current_state': True,
        'batch_timestamp_is_row_intake_time': False,
        'event_limit': 100,
        'worklist': asdict(stored),
        'timeline': [{'kind': entry.kind, 'source': asdict(entry.source)} for entry in timeline],
    }
    content = json.dumps(payload, default=scalar, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(content) > MAX_AUDIT_JSON_BYTES:
        raise AuditDataError('audit_export_too_large')
    return content
