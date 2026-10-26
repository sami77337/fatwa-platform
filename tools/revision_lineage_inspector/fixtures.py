"""Invented immutable evidence; no database, real cases, approvals or source files."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink
from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import (
    ReviewBatchOption,
    ReviewWorklist,
    StoredReference,
    StoredReviewEvent,
    StoredReviewRow,
)

SCENARIOS = (
    "consistent",
    "revision-order",
    "case-mismatch",
    "source-mismatch",
    "event-order",
    "reference-mismatch",
    "missing-workflow",
)
FIXTURE_ID = "revision-lineage.synthetic.v1"


@dataclass(frozen=True, slots=True)
class SyntheticFixture:
    record: DraftRecord
    workflow: ReviewWorklist | None
    source_payload: bytes
    expected_case_id: str
    expected_row_id: UUID
    expected_batch_id: UUID


def synthetic_fixture(scenario: str = "consistent") -> SyntheticFixture:
    """Return a repeatable, caller-owned DTO graph and its exact UTF-8 source."""
    if scenario not in SCENARIOS:
        raise ValueError("unknown_synthetic_scenario")
    reference = ReferenceLink(**dict(c.SOURCE_IDENTITY), source_id="wave7-title-1")
    intake = IntakeItem(
        "SYN-LINEAGE-001",
        "  سِجل تقني اصطناعي.\r\nلا سؤال فقهي هنا.  ",
        "https://example.invalid/synthetic-lineage",
        "Invented source attribution; no person or scholarly ruling.",
        (reference,),
    )
    raw = json.dumps(
        {"schema": c.PAYLOAD_SCHEMA, "synthetic_fixtures_only": True, "items": [asdict(intake)]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
    source = parsed.item_sources[0]
    pointer = parsed.reference_sources[0][0]
    snapshot = Revision(
        1,
        "synthetic_snapshot",
        "Synthetic editor label",
        "Technical fixture only",
        State.PREPARATION,
        "عنوان اختبار تقني",
        "  نص تقني أول.\r\n",
        (reference,),
        "",
    )
    record = DraftRecord(
        intake,
        (snapshot, replace(snapshot, number=2, answer="  نص تقني ثانٍ.\r\n")),
    )
    when = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
    first = StoredReviewEvent(
        UUID(int=31),
        UUID(int=41),
        "start_review",
        "UNREVIEWED",
        "IN_REVIEW",
        "Synthetic technical event",
        when + timedelta(minutes=1),
    )
    second = StoredReviewEvent(
        UUID(int=32),
        UUID(int=42),
        "request_changes",
        "IN_REVIEW",
        "NEEDS_CHANGES",
        "Synthetic technical event",
        when + timedelta(minutes=2),
    )
    row = StoredReviewRow(
        UUID(int=11),
        UUID(int=1),
        1,
        intake.external_id,
        intake.question,
        source.text,
        source.start,
        source.end,
        "READY_FOR_EDITOR",
        "NEEDS_CHANGES",
        intake.prepared_clip_url,
        (
            StoredReference(
                UUID(int=21), pointer.text, pointer.start, pointer.end, "UNVERIFIED", ""
            ),
        ),
        (second, first),
        False,
    )
    if scenario == "revision-order":
        record = replace(record, history=tuple(reversed(record.history)))
    elif scenario == "case-mismatch":
        row = replace(row, external_id="SYN-LINEAGE-002")
    elif scenario == "source-mismatch":
        row = replace(row, original_row=row.original_row + " ")
    elif scenario == "event-order":
        row = replace(row, events=tuple(reversed(row.events)))
    elif scenario == "reference-mismatch":
        row = replace(row, references=(replace(row.references[0], source_byte_start=0),))
    workflow = ReviewWorklist(
        (ReviewBatchOption(row.batch_id, when),),
        row.batch_id,
        (row,),
        row,
        1,
        1,
        1,
        1,
        20,
        "",
        "exact",
        "",
        "",
    )
    return SyntheticFixture(
        record,
        None if scenario == "missing-workflow" else workflow,
        raw,
        intake.external_id,
        UUID(int=11),
        UUID(int=1),
    )
