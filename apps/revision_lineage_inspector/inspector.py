"""Bounded consistency observations, never a reconstructed revision/event history.

The caller declares synthetic inputs; this is not proof of their origin. Neither
the snapshot DTO nor the workflow event DTO contains a link to the other. Matching
external labels or timestamps cannot fill that missing relationship.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import UUID

from apps.editorial_demo.workflow_audit import AuditDataError
from apps.editorial_demo.workflow_audit_provenance import build_audit_provenance
from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink, parse_intake, text
from apps.fatwa_drafts.revision_audit import build_revision_audit
from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import (
    ReviewBatchOption,
    ReviewWorklist,
    StoredReference,
    StoredReviewEvent,
    StoredReviewRow,
)
from apps.revision_core.revision_history import HistoryDataError

MAX_REPORT_BYTES = 64 * 1024
MAX_SOURCE_TEXT = c.MAX_INPUT_BYTES


class LineageInputError(ValueError):
    """Static error codes only; submitted content is never reflected."""


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    status: str


@dataclass(frozen=True, slots=True)
class LineageReport:
    checks: tuple[Check, ...]
    revision_numbers: tuple[int, ...]
    event_count: int
    reference_count: int
    events_truncated: bool | None

    @property
    def status(self) -> str:
        return (
            "INCONSISTENT"
            if any(check.status == "FAIL" for check in self.checks)
            else "CONSISTENT_WITH_LIMITATIONS"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "fatwa.revision-lineage-inspector.v1",
            "scope": c.SYNTHETIC_SCOPE,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
            "revision_numbers": list(self.revision_numbers),
            "snapshot_count": len(self.revision_numbers),
            "event_count": self.event_count,
            "reference_count": self.reference_count,
            "events_truncated": self.events_truncated,
            "complete_history": False,
            "events_are_text_snapshots": False,
            "references_are_current_workflow_state": True,
            "synthetic_declaration_is_proof": False,
            "authorization_granted": False,
            "scholarly_approval": False,
            "deployment": "NOT_DEPLOYED",
            "gates": "GATES_HOLD",
        }


def serialize_report(report: LineageReport) -> bytes:
    if (
        type(report) is not LineageReport
        or type(report.checks) is not tuple
        or len(report.checks) > 64
        or type(report.revision_numbers) is not tuple
        or not 1 <= len(report.revision_numbers) <= 100
        or any(
            type(number) is not int or not 1 <= number <= 999999
            for number in report.revision_numbers
        )
        or type(report.event_count) is not int
        or not 0 <= report.event_count <= 100
        or type(report.reference_count) is not int
        or not 0 <= report.reference_count <= 10000
        or report.events_truncated is not None
        and type(report.events_truncated) is not bool
    ):
        raise LineageInputError("invalid_report")
    for check in report.checks:
        if (
            type(check) is not Check
            or type(check.code) is not str
            or not 1 <= len(check.code) <= 100
            or not check.code.isascii()
            or check.status not in ("PASS", "FAIL", "UNAVAILABLE")
        ):
            raise LineageInputError("invalid_report")
    content = json.dumps(
        report.to_dict(),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    if len(content) > MAX_REPORT_BYTES:
        raise LineageInputError("report_limit")
    return content


def _string(value: object, limit: int, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not str or len(value) > limit:
        raise LineageInputError("invalid_or_unbounded_text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise LineageInputError("invalid_unicode") from None


def _reference(reference: object) -> None:
    if type(reference) is not ReferenceLink:
        raise LineageInputError("invalid_revision_reference")
    for field in ReferenceLink.__dataclass_fields__:
        _string(getattr(reference, field), 100)


def _record_shape(record: object) -> None:
    if (
        type(record) is not DraftRecord
        or type(record.intake) is not IntakeItem
        or type(record.history) is not tuple
        or not 1 <= len(record.history) <= 100
    ):
        raise LineageInputError("invalid_or_unbounded_history")
    item = record.intake
    for value, limit in (
        (item.external_id, 100),
        (item.question, 20000),
        (item.prepared_clip_url, 2048),
        (item.staff_notes, 20000),
    ):
        _string(value, limit)
    if type(item.reference_links) is not tuple or len(item.reference_links) > 100:
        raise LineageInputError("invalid_or_unbounded_intake_references")
    for reference in item.reference_links:
        _reference(reference)
    for revision in record.history:
        if (
            type(revision) is not Revision
            or type(revision.number) is not int
            or not 1 <= revision.number <= 999999
            or type(revision.state) is not State
            or type(revision.reference_links) is not tuple
            or len(revision.reference_links) > 100
        ):
            raise LineageInputError("invalid_revision")
        for value, limit in (
            (revision.action, 100),
            (revision.human_editor, 200),
            (revision.editorial_note, 2000),
            (revision.title, 10000),
            (revision.answer, 10000),
            (revision.reviewer_notes, 10000),
        ):
            _string(value, limit)
        for reference in revision.reference_links:
            _reference(reference)


def _dated(value: object) -> None:
    if type(value) is not datetime:
        raise LineageInputError("invalid_event_timestamp")
    try:
        if value.utcoffset() is None:
            raise LineageInputError("invalid_event_timestamp")
        value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise LineageInputError("invalid_event_timestamp") from None


def _workflow_shape(workflow: object) -> None:
    if (
        type(workflow) is not ReviewWorklist
        or type(workflow.rows) is not tuple
        or type(workflow.batches) is not tuple
        or len(workflow.batches) > 101
        or type(workflow.page_size) is not int
        or not 1 <= workflow.page_size <= 50
        or len(workflow.rows) > workflow.page_size
        or workflow.batch_id is not None
        and type(workflow.batch_id) is not UUID
    ):
        raise LineageInputError("invalid_or_unbounded_workflow")
    for value in (workflow.total_count, workflow.matched_count, workflow.page, workflow.page_count):
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise LineageInputError("invalid_workflow_counts")
    for value in (workflow.q, workflow.mode, workflow.intake_status, workflow.review_status):
        _string(value, 100)
    for batch in workflow.batches:
        if type(batch) is not ReviewBatchOption or type(batch.id) is not UUID:
            raise LineageInputError("invalid_batch")
        _dated(batch.created_at)
    for row in (*workflow.rows, *((workflow.row,) if workflow.row is not None else ())):
        if (
            type(row) is not StoredReviewRow
            or type(row.id) is not UUID
            or type(row.batch_id) is not UUID
            or type(row.references) is not tuple
            or len(row.references) > 100
            or type(row.events) is not tuple
            or len(row.events) > 100
            or type(row.events_truncated) is not bool
        ):
            raise LineageInputError("invalid_or_unbounded_workflow_row")
        for value in (row.row_ordinal, row.source_byte_start, row.source_byte_end):
            if type(value) is not int or not 0 <= value <= MAX_SOURCE_TEXT:
                raise LineageInputError("invalid_source_position")
        for value, limit in (
            (row.external_id, 100),
            (row.question, 20000),
            (row.prepared_clip_url, 2048),
        ):
            _string(value, limit, nullable=True)
        _string(row.original_row, MAX_SOURCE_TEXT)
        _string(row.intake_status, 100)
        _string(row.review_status, 100)
        for reference in row.references:
            if type(reference) is not StoredReference or type(reference.id) is not UUID:
                raise LineageInputError("invalid_workflow_reference")
            for value in (reference.source_byte_start, reference.source_byte_end):
                if type(value) is not int or not 0 <= value <= MAX_SOURCE_TEXT:
                    raise LineageInputError("invalid_source_position")
            _string(reference.original_pointer, MAX_SOURCE_TEXT)
            _string(reference.reference_status, 100)
            _string(reference.citation_text, MAX_SOURCE_TEXT)
        for event in row.events:
            if (
                type(event) is not StoredReviewEvent
                or type(event.id) is not UUID
                or type(event.operation_id) is not UUID
            ):
                raise LineageInputError("invalid_workflow_event")
            _dated(event.created_at)
            for value in (event.action, event.from_status, event.to_status):
                _string(value, 100)
            _string(event.reason, c.MAX_REASON_CHARS)


def inspect_lineage(
    record: DraftRecord,
    *,
    expected_case_id: str,
    workflow: ReviewWorklist | None = None,
    expected_row_id: UUID | None = None,
    expected_batch_id: UUID | None = None,
    source_payload: bytes | None = None,
    synthetic_fixtures_only: bool = False,
) -> LineageReport:
    """Inspect supplied evidence only; perform no loading, writes or resolution.

    Snapshot order must increase; gaps are retained and marked unavailable.
    Events use the authoritative reader's newest-first UTC/id ordering. Event
    continuity is assessed only within this supplied window, never as a claim of
    complete history. Explicit UUID pins select workflow evidence; even matching
    pins and external IDs cannot establish the missing draft-to-workflow link.
    Reference provenance PASS checks pointer shape only. Source membership PASS
    checks all six identity fields against supplied intake pointers, not external
    resolution. Newly added pointers outside that source are UNAVAILABLE because
    an immutable edit may legitimately introduce a reference from another source.
    """
    if synthetic_fixtures_only is not True:
        raise LineageInputError("synthetic_fixture_acknowledgement_required")
    if type(expected_case_id) is not str or c.valid_external_id(expected_case_id) is None:
        raise LineageInputError("invalid_expected_case_identity")
    for value in (expected_row_id, expected_batch_id):
        if value is not None and type(value) is not UUID:
            raise LineageInputError("invalid_expected_workflow_identity")
    if (expected_row_id is None) != (expected_batch_id is None):
        raise LineageInputError("incomplete_expected_workflow_identity")
    if source_payload is not None and (
        type(source_payload) is not bytes or not 1 <= len(source_payload) <= c.MAX_INPUT_BYTES
    ):
        raise LineageInputError("invalid_or_unbounded_source_payload")
    _record_shape(record)
    if workflow is not None:
        _workflow_shape(workflow)
    checks: list[Check] = []

    def check(code: str, value: bool | None) -> None:
        checks.append(Check(code, "UNAVAILABLE" if value is None else "PASS" if value else "FAIL"))

    numbers = tuple(revision.number for revision in record.history)
    try:
        build_revision_audit(record, synthetic_fixtures_only=True)
        check("revision_contract", True)
    except (HistoryDataError, TypeError, ValueError):
        check("revision_contract", False)
    check("revision_order", all(a < b for a, b in zip(numbers, numbers[1:])))
    check("revision_gaps", True if all(b == a + 1 for a, b in zip(numbers, numbers[1:])) else None)
    check("case_identity", record.intake.external_id == expected_case_id)
    try:
        record.intake.__post_init__()
        for revision in record.history:
            for reference in revision.reference_links:
                reference.__post_init__()
        check("reference_provenance", True)
    except (TypeError, ValueError):
        check("reference_provenance", False)

    row = workflow.row if workflow is not None else None
    provenance = None
    if workflow is not None:
        try:
            provenance = build_audit_provenance(workflow, synthetic_fixtures_only=True)
            check("workflow_contract", True)
        except (AuditDataError, TypeError, ValueError):
            check("workflow_contract", False)
    else:
        check("workflow_contract", None)
    check(
        "workflow_identity",
        None
        if row is None or expected_row_id is None
        else (
            row.id == expected_row_id
            and row.batch_id == expected_batch_id
            and workflow.batch_id == expected_batch_id
        ),
    )
    check("workflow_external_id", None if row is None else row.external_id == expected_case_id)
    if row is not None:
        row_bytes = row.original_row.encode("utf-8")
        check(
            "workflow_source_span",
            row.row_ordinal >= 1
            and row.source_byte_end > row.source_byte_start
            and (row.source_byte_end - row.source_byte_start == len(row_bytes)),
        )
        check(
            "workflow_reference_contract",
            (
                len({ref.id for ref in row.references}) == len(row.references)
                and all(
                    ref.reference_status in c.ReferenceStatus
                    and (
                        ref.reference_status == c.ReferenceStatus.VERIFIED or not ref.citation_text
                    )
                    and row.source_byte_start
                    <= ref.source_byte_start
                    < ref.source_byte_end
                    <= row.source_byte_end
                    and ref.source_byte_end - ref.source_byte_start
                    == len(ref.original_pointer.encode("utf-8"))
                    and row_bytes[
                        ref.source_byte_start - row.source_byte_start : ref.source_byte_end
                        - row.source_byte_start
                    ]
                    == ref.original_pointer.encode("utf-8")
                    for ref in row.references
                )
                and all(
                    before.source_byte_end <= after.source_byte_start
                    for before, after in zip(row.references, row.references[1:])
                )
            ),
        )

        def key(event: StoredReviewEvent) -> tuple[datetime, UUID]:
            return event.created_at.astimezone(timezone.utc), event.id

        check("event_order", all(key(a) > key(b) for a, b in zip(row.events, row.events[1:])))
        chronological = tuple(sorted(row.events, key=key))
        transitions_valid = True
        for event in chronological:
            try:
                transitions_valid &= (
                    c.next_review_status(event.from_status, event.action) == event.to_status
                )
                text(event.reason, "reason", limit=c.MAX_REASON_CHARS)
            except (TypeError, ValueError):
                transitions_valid = False
        check("event_transitions", transitions_valid)
        # UUID ties order the reader presentation, not causal transitions. Even
        # valid individual events cannot prove a chain through a tied instant.
        tied_instants = any(
            key(before)[0] == key(after)[0]
            for before, after in zip(chronological, chronological[1:])
        )
        latest_tied = len(chronological) > 1 and (
            key(chronological[-2])[0] == key(chronological[-1])[0]
        )
        check(
            "event_chain",
            None
            if tied_instants
            else all(
                before.to_status == after.from_status
                for before, after in zip(chronological, chronological[1:])
            ),
        )
        check(
            "event_current_state",
            None
            if not chronological or latest_tied
            else (chronological[-1].to_status == row.review_status),
        )
        check(
            "event_after_batch",
            None
            if provenance is None or provenance.batch is None
            else all(
                key(event)[0] >= provenance.batch.created_at.astimezone(timezone.utc)
                for event in chronological
            ),
        )
    else:
        for code in (
            "workflow_source_span",
            "workflow_reference_contract",
            "event_order",
            "event_transitions",
            "event_chain",
            "event_current_state",
            "event_after_batch",
        ):
            check(code, None)

    parsed = None
    if source_payload is not None:
        try:
            parsed = c.parse_synthetic_payload(source_payload, synthetic_fixtures_only=True)
            check("source_contract", True)
        except c.ContractError:
            check("source_contract", False)
    else:
        check("source_contract", None)
    source = None
    if parsed is not None and row is not None:
        if 1 <= row.row_ordinal <= len(parsed.items):
            source = parsed.item_sources[row.row_ordinal - 1]
        check(
            "source_row_attribution",
            source is not None
            and (row.source_byte_start, row.source_byte_end, row.original_row)
            == (source.start, source.end, source.text),
        )
        source_refs = parsed.reference_sources[row.row_ordinal - 1] if source is not None else ()
        check(
            "source_reference_attribution",
            source is not None
            and len(source_refs) == len(row.references)
            and len({ref.id for ref in row.references}) == len(row.references)
            and all(
                (ref.source_byte_start, ref.source_byte_end, ref.original_pointer)
                == (pointer.start, pointer.end, pointer.text)
                for ref, pointer in zip(row.references, source_refs)
            ),
        )
        original = parsed.items[row.row_ordinal - 1] if source is not None else None
        check(
            "workflow_source_fields",
            isinstance(original, dict)
            and (row.external_id, row.question, row.prepared_clip_url)
            == (
                original.get("external_id"),
                original.get("question"),
                original.get("prepared_clip_url"),
            ),
        )
        if source is not None:
            try:
                envelope = (
                    b'{"schema":"fatwa.prepared-intake.v1","items":['
                    + source.text.encode("utf-8")
                    + b"]}"
                )
                source_item = parse_intake(envelope)[0]
                check("draft_source_attribution", record.intake == source_item)
                check(
                    "snapshot_reference_source_membership",
                    True
                    if all(
                        ref in source_item.reference_links
                        for revision in record.history
                        for ref in revision.reference_links
                    )
                    else None,
                )
            except (TypeError, ValueError):
                check("draft_source_attribution", False)
                check("snapshot_reference_source_membership", None)
        else:
            check("draft_source_attribution", False)
            check("snapshot_reference_source_membership", None)
    else:
        for code in (
            "source_row_attribution",
            "source_reference_attribution",
            "workflow_source_fields",
            "draft_source_attribution",
            "snapshot_reference_source_membership",
        ):
            check(code, None)
    for code in (
        "snapshot_event_relationship",
        "draft_workflow_binding",
        "authenticated_attribution",
        "complete_event_history",
        "historical_workflow_references",
        "reference_resolution",
        "source_payload_batch_binding",
    ):
        check(code, None)
    return LineageReport(
        tuple(checks),
        numbers,
        len(row.events) if row is not None else 0,
        sum(len(revision.reference_links) for revision in record.history),
        row.events_truncated if row is not None else None,
    )
