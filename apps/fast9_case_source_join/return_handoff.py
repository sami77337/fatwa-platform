"""Read-only preparation of a synthetic human answer for return-to-origin.

Readiness is not approval. A downstream trusted MUFTI receipt verifier remains
mandatory; this module issues no Authority, approval, intent, or journal note.

The answer content fingerprint is SHA-256 of the UTF-8 encoding of compact JSON
``["human-answer-content.v1", draft.title, draft.body]``, with ensure_ascii=False
and separators=(",", ":"). Unicode and whitespace are preserved exactly. This
versioned content identity is distinct from the AnswerDraft append-only chain
digest pinned by technical notes, and from the fixed intake reading digest.
"""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from apps.delivery_planner.approval import CurrentEvidence
from apps.delivery_planner.planner import InvalidPlan
from apps.editorial_export.services import require_development

from .answer_drafts import CASE_KEY, AnswerDraft
from .draft_source_review import inspect_draft_source
from .source_journal import history_digest, read_case_review


@dataclass(frozen=True, slots=True)
class ReturnCandidate:
    case_key: str
    draft: AnswerDraft | None
    evidence: CurrentEvidence | None
    source_count: int
    source_channel: str | None
    source_account: str | None
    source_conversation: str | None
    source_reference: str | None
    reading_current: bool
    technical_review_current: bool
    blockers: tuple[str, ...]


def read_return_candidate(
    directory: Path, *, synthetic_fixtures_only: bool = False
) -> ReturnCandidate:
    """Evaluate one verified journal snapshot without hiding storage failures.

    Absent source/draft suppress dependent preparation blockers. Evidence, when
    present, describes the current source and latest human draft, even if stale.
    Use read_current_evidence at reservation time to reject every preparation
    blocker, including technical staleness outside CurrentEvidence's booleans.
    """
    require_development(synthetic_fixtures_only)
    snapshot = read_case_review(directory, synthetic_fixtures_only=synthetic_fixtures_only)
    events = snapshot.events
    first = events[0] if events else None
    draft = snapshot.drafts[-1] if snapshot.drafts else None
    source_digest = history_digest(events) or ""
    pending = bool(snapshot.clarifications and snapshot.clarifications[-1].kind == "request")
    deleted = bool(events and events[-1].body_utf8 is None)
    note = snapshot.draft_notes[-1] if snapshot.draft_notes else None
    change_open = bool(note and note.action == "request")
    draft_current = bool(
        events
        and draft
        and (draft.source_count, draft.source_digest, draft.reply_digest)
        == (len(events), source_digest, snapshot.reply_digest)
    )
    receipt = snapshot.receipt
    reading_current = False
    if events and receipt:
        # A reading acknowledges fixed intake revision 1, not the authored answer.
        intake = inspect_draft_source(CASE_KEY, 1, events, synthetic_fixtures_only=True)
        reading_current = (
            receipt.count,
            receipt.source_digest,
            receipt.reply_digest,
            receipt.draft_digest,
        ) == (len(events), source_digest, snapshot.reply_digest, intake.draft_revision_sha256)
    technical_current = bool(
        draft_current
        and not pending
        and note
        and note.action == "confirm"
        and (note.revision, note.draft_digest) == (draft.revision, draft.digest)
    )
    evidence = None
    if events and draft:
        content = json.dumps(
            ["human-answer-content.v1", draft.title, draft.body],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        evidence = CurrentEvidence(
            case_key=CASE_KEY,
            answer_revision=draft.revision,
            answer_sha256=sha256(content).hexdigest(),
            source_digest=source_digest,
            reply_digest=snapshot.reply_digest,
            source_deleted=deleted,
            clarification_pending=pending,
            change_request_open=change_open,
        )
    blockers = []
    if not events:
        blockers.append("source_missing")
    if draft is None:
        blockers.append("answer_missing")
    if deleted:
        blockers.append("source_deleted")
    if pending:
        blockers.append("clarification_pending")
    if events and draft:
        if not draft_current:
            blockers.append("answer_evidence_stale")
        if not reading_current:
            blockers.append("source_reading_required")
        if change_open:
            blockers.append("change_request_open")
        if not technical_current:
            blockers.append("technical_review_required")
    return ReturnCandidate(
        case_key=CASE_KEY,
        draft=draft,
        evidence=evidence,
        source_count=len(events),
        source_channel=first.channel if first else None,
        source_account=first.account if first else None,
        source_conversation=first.conversation if first else None,
        source_reference=first.source_ref if first else None,
        reading_current=reading_current,
        technical_review_current=technical_current,
        blockers=tuple(blockers),
    )


def read_current_evidence(
    directory: Path, case_key: str, *, synthetic_fixtures_only: bool = False
) -> CurrentEvidence:
    """Fail closed on wrong case or the first stable preparation blocker."""
    require_development(synthetic_fixtures_only)
    if type(case_key) is not str or case_key != CASE_KEY:
        raise InvalidPlan("return_case_mismatch")
    candidate = read_return_candidate(directory, synthetic_fixtures_only=synthetic_fixtures_only)
    if candidate.blockers:
        raise InvalidPlan(candidate.blockers[0])
    if candidate.evidence is None:
        raise InvalidPlan("answer_missing")
    return candidate.evidence
