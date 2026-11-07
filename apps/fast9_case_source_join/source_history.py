"""Replay one fixed synthetic Wave7 source message without performing any I/O."""

import re
from dataclasses import dataclass, replace
from hashlib import sha256

from apps.intake_workflow.contracts import parse_synthetic_payload
from apps.intake_workflow.fixtures import synthetic_payload

# These envelope identifiers are invented. Wave7 contains rows, not provider messages.
# Some messages deliberately share the same unscoped ID.
_ORIGINS = {
    "intake-1": (1, "fixture-account-a", "fixture-thread-a", "fixture-msg-11"),
    "intake-4": (4, "fixture-account-a", "fixture-thread-b", "fixture-msg-11"),
    "intake-7": (7, "fixture-account-b", "fixture-thread-a", "fixture-msg-11"),
}
CORRECTION_BODIES = (
    "  تَصحيحٌ اصطناعيّ أوّل\r\nالسطر الثاني  ".encode("utf-8"),
    "تصحيحٌ اصطناعيّ ثانٍ".encode("utf-8"),
)
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", re.ASCII)


@dataclass(frozen=True, slots=True)
class SourceEvent:
    event_id: str
    case_key: str
    channel: str
    account: str
    conversation: str
    source_ref: str
    kind: str
    prior_event_id: str | None
    body_utf8: bytes | None
    row_sha256: str


def source_receipt(case_key: str) -> SourceEvent:
    """Anchor the synthetic envelope to the actual Wave7 row and decoded question."""
    if type(case_key) is not str or case_key not in _ORIGINS:
        raise ValueError("unknown_fixture_case")
    ordinal, account, conversation, source_ref = _ORIGINS[case_key]
    parsed = parse_synthetic_payload(synthetic_payload(), synthetic_fixtures_only=True)
    row = parsed.item_sources[ordinal - 1]
    body = parsed.items[ordinal - 1]["question"].encode("utf-8")
    return SourceEvent(
        f"received-{case_key}",
        case_key,
        "wave7-synthetic",
        account,
        conversation,
        source_ref,
        "received",
        None,
        body,
        sha256(parsed.raw[row.start : row.end]).hexdigest(),
    )


def validate_event_shape(event: SourceEvent) -> None:
    if type(event) is not SourceEvent or any(
        type(value) is not str
        for value in (
            event.event_id,
            event.case_key,
            event.channel,
            event.account,
            event.conversation,
            event.source_ref,
            event.kind,
            event.row_sha256,
        )
    ):
        raise ValueError("invalid_event")
    if (
        not _EVENT_ID.fullmatch(event.event_id)
        or (event.prior_event_id is not None and type(event.prior_event_id) is not str)
        or (event.body_utf8 is not None and type(event.body_utf8) is not bytes)
    ):
        raise ValueError("invalid_event")


def replay_source_history(
    events: list[SourceEvent] | tuple[SourceEvent, ...], *, synthetic_fixtures_only: bool = False
) -> tuple[SourceEvent, ...]:
    """Reconstruct a single ordered lineage. Exact retransmissions occupy one position."""
    if synthetic_fixtures_only is not True:
        raise ValueError("synthetic_opt_in_required")
    if type(events) not in (list, tuple) or not 1 <= len(events) <= 128:
        raise ValueError("expected_1_to_128_events")
    history: dict[str, SourceEvent] = {}
    for event in events:
        validate_event_shape(event)
        if event.event_id in history:
            if history[event.event_id] != event:
                raise ValueError("event_id_conflict")
            continue
        if not history:
            if source_receipt(event.case_key) != event:
                raise ValueError("original_receipt_mismatch")
        else:
            root = next(iter(history.values()))
            previous = next(reversed(history.values()))
            if (
                event.case_key != root.case_key
                or event.row_sha256 != root.row_sha256
                or event.channel != root.channel
                or event.account != root.account
                or event.conversation != root.conversation
                or event.source_ref != root.source_ref
            ):
                raise ValueError("source_scope_mismatch")
            if previous.kind == "deleted" or event.prior_event_id != previous.event_id:
                raise ValueError("invalid_predecessor")
            if event.kind == "corrected":
                if event.body_utf8 not in (*CORRECTION_BODIES, root.body_utf8):
                    raise ValueError("unknown_fixture_body")
            elif event.kind != "deleted" or event.body_utf8 is not None:
                raise ValueError("invalid_change")
        history[event.event_id] = event
    return tuple(history.values())


def sample_source_events(case_key: str, sample: str) -> tuple[SourceEvent, ...]:
    """Return the fixed local example prefix for this case, without writes."""
    if sample not in ("received", "corrected", "deleted", "restored"):
        raise ValueError("unknown_fixture_sample")
    first = source_receipt(case_key)
    if sample == "received":
        return (first,)
    edit = replace(
        first,
        event_id="edit-example",
        prior_event_id=first.event_id,
        kind="corrected",
        body_utf8=CORRECTION_BODIES[0],
    )
    if sample == "corrected":
        return first, edit
    if sample == "deleted":
        last = replace(
            edit,
            event_id="delete-example",
            prior_event_id=edit.event_id,
            kind="deleted",
            body_utf8=None,
        )
    else:
        last = replace(
            edit,
            event_id="restore-example",
            prior_event_id=edit.event_id,
            body_utf8=first.body_utf8,
        )
    return first, edit, last
