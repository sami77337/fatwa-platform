"""Read-only comparison of a fixed intake draft with its fabricated source history."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.editorial_workbench.services import build_cases

from .source_history import SourceEvent, replay_source_history


@dataclass(frozen=True, slots=True)
class DraftSourceObservation:
    case_key: str
    draft_revision: int
    draft_revision_sha256: str
    original_row_sha256: str
    original_event_id: str
    last_supplied_event_id: str
    original_question_sha256: str
    last_supplied_question_sha256: str | None
    changed_event_ids: tuple[str, ...]
    status: str


def inspect_draft_source(
    case_key: str,
    draft_revision: int,
    events: tuple[SourceEvent, ...],
    *,
    synthetic_fixtures_only: bool = False,
) -> DraftSourceObservation:
    """Inspect the source bytes used by the actual fixed receipt-stage draft.

    A source change is a reason for a human to check the facts. This does not
    classify materiality, record acknowledgment or authorize approval. The
    result covers the supplied event prefix. It is not a freshness claim.
    """
    if type(case_key) is not str or type(draft_revision) is not int or draft_revision < 1:
        raise ValueError("invalid_draft_identity")
    history = replay_source_history(events, synthetic_fixtures_only=synthetic_fixtures_only)
    if not history or any(event.case_key != case_key for event in history):
        raise ValueError("source_case_mismatch")
    case = next((item for item in build_cases() if item.key == case_key), None)
    if case is None or case.record is None or case.record.current.number != draft_revision:
        raise ValueError("draft_revision_unavailable")

    first = history[0]
    original = case.record.intake.question.encode("utf-8")
    if (
        first.row_sha256 != sha256(case.raw_source.encode("utf-8")).hexdigest()
        or first.body_utf8 != original
    ):
        raise ValueError("draft_source_mismatch")

    # Keep intervening changes visible even if a later event restores the text.
    changes = tuple(
        current.event_id
        for previous, current in zip(history, history[1:])
        if previous.body_utf8 != current.body_utf8
    )
    latest = history[-1].body_utf8
    if latest is None:
        status = "SOURCE_DELETED_REVIEW_NEEDED"
    elif changes:
        status = "SOURCE_TEXT_CHANGED_REVIEW_NEEDED"
    else:
        status = "SOURCE_TEXT_UNCHANGED"
    revision_bytes = json.dumps(
        asdict(case.record.current),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return DraftSourceObservation(
        case_key=case_key,
        draft_revision=draft_revision,
        draft_revision_sha256=sha256(revision_bytes).hexdigest(),
        original_row_sha256=first.row_sha256,
        original_event_id=first.event_id,
        last_supplied_event_id=history[-1].event_id,
        original_question_sha256=sha256(original).hexdigest(),
        last_supplied_question_sha256=sha256(latest).hexdigest() if latest is not None else None,
        changed_event_ids=changes,
        status=status,
    )
