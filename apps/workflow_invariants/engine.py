"""Deterministic event replay over allowlisted FAST5 fixtures, in memory only.

An event is a technical command, never a permission grant or scholarly approval.
No caller-supplied record, text, actor, database, clock or network is used.
"""

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any

from apps.editorial_workbench.services import WorkbenchCase, build_cases
from apps.fatwa_drafts.domain import DraftRecord, transition
from apps.fatwa_drafts.intake import ValidationError
from apps.intake_workflow.contracts import (
    CONTRACT_VERSION,
    REVIEW_TRANSITIONS,
    ContractError,
    idempotency_decision,
    next_review_status,
    valid_external_id,
    validate_verified_identity,
)
from apps.revision_core.revision_history import HistoryDataError, build_history
from apps.workflow_rehearsal.services import CASE_KEYS, build_rehearsal

SCHEMA = "fatwa.workflow-invariants.v1"
MAX_EVENTS = 64
MAX_INPUT_BYTES = 1_000_000
HUMAN = {
    "human_editor": "محاكاة تقنية اصطناعية",
    "editorial_note": "إسقاط في الذاكرة فقط؛ لا اعتماد أو نشر.",
}
GATES = {
    "Gate B": "NOT_PASSED",
    "C/D/E": "HOLD",
    "Phase01": "BLOCKED",
    "scope": "SCOPE_DEVIATION_HOLD",
    "deployment": "NOT_DEPLOYED",
}


class ReplayError(ValueError):
    """The input cannot describe a bounded synthetic replay."""


def canonical_bytes(value: Any) -> bytes:
    """Exact Unicode preservation, canonical object order; no float/NaN coercion."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _json_value(value: Any, depth: int = 0) -> None:
    # Explicit types avoid bool==1, tuple/list and custom-object equality aliases.
    if depth > 30:
        raise ReplayError("input: nesting_limit")
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int and abs(value) <= 2**53 - 1:
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ReplayError("input: unsupported_json_value")


def _case(key: str) -> WorkbenchCase:
    if type(key) is not str or key not in CASE_KEYS:
        raise ReplayError("input: unknown_fixed_case")
    return next(case for case in build_cases() if case.key == key)


def source_identity(case: WorkbenchCase) -> dict:
    """Pin row identity separately from nonunique external IDs and payload hashes."""
    return {
        "case_key": case.key,
        "external_id": case.external_id,
        "payload_sha256": case.payload_sha256,
        "source_sha256": sha256(case.raw_source.encode("utf-8")).hexdigest(),
        "source_start": case.source_start,
        "source_end": case.source_end,
        "reference_identities": [
            {
                "source": ref["source"],
                "source_sha256": ref["source_sha256"],
                "verified_identity": ref["verified_identity"],
            }
            for ref in case.references
        ],
    }


def snapshot(record: DraftRecord | None, review: str) -> dict:
    return json.loads(
        canonical_bytes({"record": asdict(record) if record else None, "review": review})
    )


def state_token(state: dict) -> dict:
    current = state["record"]["history"][-1] if state["record"] else None
    return {
        "preparation": current["state"] if current else None,
        "revision": current["number"] if current else None,
        "review": state["review"],
        "state_sha256": _digest(state),
    }


def make_event(
    case_key: str,
    sequence: int,
    dimension: str,
    action: str,
    *,
    before: dict | None = None,
    event_id: str | None = None,
) -> dict:
    """Build a command pinned to a fixed source and an exact before snapshot."""
    case = _case(case_key)
    return json.loads(
        canonical_bytes(
            {
                "event_id": event_id if event_id is not None else f"event-{sequence}",
                "sequence": sequence,
                "dimension": dimension,
                "action": action,
                "source_identity": source_identity(case),
                "expected_state": state_token(
                    before if before is not None else snapshot(case.record, "UNREVIEWED")
                ),
            }
        )
    )


def _apply(record: DraftRecord | None, review: str, event: dict) -> tuple:
    if record is None:
        raise ReplayError("event: no_draft_available")
    if event["dimension"] == "preparation":
        return transition(
            record, event["action"], expected_revision=record.current.number, **HUMAN
        ), review
    return record, next_review_status(review, event["action"]).value


def _changes(before: Any, after: Any, path: str = "") -> list[str]:
    """JSON Pointer paths, including list positions; exact types and text matter."""
    if type(before) is not type(after):
        return [path or "/"]
    if isinstance(before, dict):
        paths = []
        for key in sorted(before.keys() | after.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            paths.extend(
                [child]
                if key not in before or key not in after
                else _changes(before[key], after[key], child)
            )
        return paths
    if isinstance(before, list):
        paths = []
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            paths.extend(
                [child]
                if index >= min(len(before), len(after))
                else _changes(before[index], after[index], child)
            )
        return paths
    return [] if before == after else [path or "/"]


def _validate_history(record: DraftRecord) -> None:
    try:
        build_history(record)
    except HistoryDataError as exc:
        raise ReplayError("invariant: invalid_history") from exc


def _invariants(
    before: DraftRecord, after: DraftRecord, old_review: str, new_review: str, event: dict
) -> None:
    checks = [
        after.intake == before.intake,
        after.unpublished,
        after.current.reference_links == before.current.reference_links,
    ]
    if event["dimension"] == "preparation":
        checks.extend(
            (
                new_review == old_review,
                after.history[:-1] == before.history,
                after.current.number == before.current.number + 1,
                after.current.state.value == event["action"],
                after.current.title == before.current.title,
                after.current.answer == before.current.answer,
                after.current.reviewer_notes == before.current.reviewer_notes,
            )
        )
    else:
        checks.extend(
            (after == before, new_review == REVIEW_TRANSITIONS.get((old_review, event["action"])))
        )
    # Reuse validation/comparison of immutable history; preserve historical gaps.
    _validate_history(after)
    if not all(checks):
        raise ReplayError("invariant: contract_result_mismatch")


def _event_schema(event: Any) -> bool:
    return (
        type(event) is dict
        and set(event)
        == {"event_id", "sequence", "dimension", "action", "source_identity", "expected_state"}
        and valid_external_id(event["event_id"]) is not None
        and type(event["sequence"]) is int
        and 1 <= event["sequence"] <= MAX_EVENTS
        and type(event["dimension"]) is str
        and event["dimension"] in ("preparation", "review")
        and type(event["action"]) is str
        and 1 <= len(event["action"]) <= 100
    )


def replay(request: dict) -> dict:
    """Replay ordered attempts; return detached JSON evidence without side effects.

    Valid source-pinned, in-order events consume their sequence even if the pure
    contract rejects them. Their IDs bind to their entire canonical command.
    Retries return the original decision without restoring its old after-state.
    Schema/source/order failures consume neither ID nor sequence.
    """
    _json_value(request)
    try:
        raw = canonical_bytes(request)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReplayError("input: invalid_json_or_unicode") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise ReplayError("input: byte_limit")
    if (
        type(request) is not dict
        or set(request) != {"schema", "synthetic_fixtures_only", "case_key", "events"}
        or request["schema"] != SCHEMA
        or request["synthetic_fixtures_only"] is not True
        or type(request["events"]) is not list
        or len(request["events"]) > MAX_EVENTS
    ):
        raise ReplayError("input: invalid_envelope")
    case = _case(request["case_key"])
    identity = source_identity(case)
    for ref in case.references:
        if ref["verified_identity"]:
            validate_verified_identity(ref["verified_identity"])
    record, review = case.record, "UNREVIEWED"
    initial = snapshot(record, review)
    if record is not None:
        _validate_history(record)
    seen = {}
    next_sequence = 1
    steps = []
    for ordinal, event in enumerate(request["events"], 1):
        before = snapshot(record, review)
        accepted, disposition, reason = False, "REJECTED", "event: invalid_schema"
        original_ordinal = None
        event_hash = _digest(event)
        try:
            if not _event_schema(event):
                raise ReplayError(reason)
            if canonical_bytes(event["source_identity"]) != canonical_bytes(identity):
                raise ReplayError("event: source_identity_mismatch")
            previous = seen.get(event["event_id"])
            decision = idempotency_decision(
                previous["event_sha256"] if previous else None, event_hash
            )
            if decision == "REPLAY":
                accepted, reason = previous["accepted"], previous["reason"]
                original_ordinal, disposition = previous["ordinal"], "REPLAY"
            else:
                if event["sequence"] != next_sequence:
                    raise ReplayError("event: out_of_order")
                next_sequence += 1
                try:
                    if canonical_bytes(event["expected_state"]) != canonical_bytes(
                        state_token(before)
                    ):
                        raise ReplayError("event: state_before_mismatch")
                    candidate, candidate_review = _apply(record, review, event)
                    _invariants(record, candidate, review, candidate_review, event)
                    record, review = candidate, candidate_review
                    accepted, disposition, reason = True, "APPLIED", "accepted_by_pure_contract"
                except (ValidationError, ContractError, ReplayError) as exc:
                    if str(exc).startswith("invariant:"):
                        raise
                    reason = str(exc)
                seen[event["event_id"]] = {
                    "event_sha256": event_hash,
                    "accepted": accepted,
                    "reason": reason,
                    "ordinal": ordinal,
                }
        except (ValidationError, ContractError, ReplayError) as exc:
            if str(exc).startswith("invariant:"):
                raise
            reason = str(exc)
        after = snapshot(record, review)
        paths = _changes(before, after)
        steps.append(
            {
                "ordinal": ordinal,
                "event": event,
                "event_sha256": event_hash,
                "accepted": accepted,
                "disposition": disposition,
                "reason": reason,
                "original_ordinal": original_ordinal,
                "before": before,
                "after": after,
                "before_sha256": _digest(before),
                "after_sha256": _digest(after),
                "state_changed": bool(paths),
                "changed_paths": paths,
            }
        )
    result = {
        "schema": SCHEMA + ".result",
        "synthetic_fixtures_only": True,
        "contract_version": CONTRACT_VERSION,
        "input_sha256": sha256(raw).hexdigest(),
        "input_hash_kind": "canonical_json",
        "source_identity": identity,
        "source": {
            "raw_text": case.raw_source,
            "start": case.source_start,
            "end": case.source_end,
            "references": list(case.references),
            "kind": "serialized_intake" if case.key == "history" else "original_row_slice",
        },
        "initial": initial,
        "final": snapshot(record, review),
        "steps": steps,
        "next_sequence": next_sequence,
        "invariants_passed": True,
        "owner_transitions": "NOT_SUPPLIED",
        "gates": GATES,
    }
    return json.loads(canonical_bytes(result))


def scenario(name: str = "rehearsal") -> dict:
    """Executable fixtures use only actual FAST5 attempts and domain transitions."""
    if name not in ("rehearsal", "preparation", "blocked"):
        raise ReplayError("input: unknown_scenario")
    key = "history" if name == "preparation" else "intake-1" if name == "blocked" else "intake-7"
    case = _case(key)
    if name == "preparation":
        attempts = [
            ("preparation", action)
            for action in (
                "needs_revision",
                "draft_preparation",
                "ready_for_future_review",
                "needs_revision",
            )
        ]
    else:
        attempts = [(step.dimension, step.action) for step in build_rehearsal(key).steps]
    record, review = case.record, "UNREVIEWED"
    events = []
    for sequence, (dimension, action) in enumerate(attempts, 1):
        event = make_event(key, sequence, dimension, action, before=snapshot(record, review))
        events.append(event)
        try:
            record, review = _apply(record, review, event)
        except (ValidationError, ContractError, ReplayError):
            pass
    return {"schema": SCHEMA, "synthetic_fixtures_only": True, "case_key": key, "events": events}
