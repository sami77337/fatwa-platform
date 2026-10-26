"""Bounded, pure projections over existing fixed prepared receipts only.

No record creation, editing, persistence, permissions, source-file I/O or network.
Internal review starts at a synthetic UNREVIEWED label, never a persisted status.
"""

import json
from dataclasses import asdict
from hashlib import sha256

from apps.editorial_workbench.batches import PreparedCase
from apps.editorial_workbench.services import build_prepared_workbench
from apps.fatwa_drafts.domain import DraftRecord, State, transition
from apps.fatwa_drafts.intake import ValidationError
from apps.intake_workflow.contracts import (
    CONTRACT_VERSION,
    ContractError,
    ReviewAction,
    next_review_status,
    validate_verified_identity,
)
from apps.revision_core.revision_history import build_history
from apps.workflow_invariants.engine import canonical_bytes, snapshot, state_token

SCHEMA = "fatwa.fast8-prepared-review.v1"
MAX_COMMANDS = 32
MAX_INPUT_BYTES = 1_000_000
_ATTRIBUTION = {
    "human_editor": "وسم محاكاة اصطناعي ثابت",
    "editorial_note": "إسقاط تقني في الذاكرة فقط؛ لا تحرير علمي أو اعتماد أو نشر.",
}


class BridgeError(ValueError):
    """The request is not a bounded, explicit synthetic projection."""


def _request_bytes(value: object) -> bytes:
    count = 0

    def check(item, depth=0):
        nonlocal count
        count += 1
        if depth > 24 or count > 100_000:
            raise BridgeError("bridge: structure_limit")
        if item is None or type(item) is bool:
            return
        if type(item) is str and len(item) <= MAX_INPUT_BYTES:
            return
        if type(item) is int and abs(item) <= 2**53 - 1:
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for key, child in item.items():
                check(key, depth + 1)
                check(child, depth + 1)
            return
        raise BridgeError("bridge: unsupported_json_value")

    check(value)
    raw = bytearray()
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        # Do not expand shared strings/containers into an unbounded full document.
        # Individual chunks are bounded by the string and integer checks above.
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            if len(raw) + len(encoded) > MAX_INPUT_BYTES:
                raise BridgeError("bridge: input_byte_limit")
            raw.extend(encoded)
    except BridgeError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BridgeError("bridge: invalid_json_or_unicode") from exc
    return bytes(raw)


def _select(key: str, acknowledged: bool):
    if acknowledged is not True:
        raise BridgeError("bridge: synthetic_acknowledgement_required")
    if type(key) is not str or not 1 <= len(key) <= 100:
        raise BridgeError("bridge: unknown_fixed_prepared_case")
    workbench = build_prepared_workbench()
    matches = [case for case in workbench.cases if case.key == key]
    if len(matches) != 1:
        raise BridgeError("bridge: unknown_fixed_prepared_case")
    case = matches[0]
    batches = [batch for batch in workbench.batches if batch.batch_id == case.batch_id]
    if len(batches) != 1:
        raise BridgeError("bridge: ambiguous_batch_identity")
    batch = batches[0]
    if (
        batch.error_code is not None
        or batch.input_sha256 != case.payload_sha256
        or sha256(batch.raw_source.encode("utf-8")).hexdigest() != case.payload_sha256
        or type(case.row_ordinal) is not int
        or not 1 <= case.row_ordinal <= batch.record_count
        or case.key != f"batch-{case.batch_id}-{case.row_ordinal}"
    ):
        raise BridgeError("bridge: invalid_source_fingerprint")
    if case.record is not None:
        build_history(case.record)
    return case, batch


def _identity(case: PreparedCase, batch) -> dict:
    # Bind every parsed source/diagnostic field, not only a reusable external ID.
    source = asdict(case)
    del source["record"]
    return {
        "case_key": case.key,
        "batch_id": case.batch_id,
        "row_ordinal": case.row_ordinal,
        "external_id": case.external_id,
        "input_format": batch.input_format,
        "payload_sha256": case.payload_sha256,
        "parsed_row_sha256": sha256(case.raw_source.encode("utf-8")).hexdigest(),
        "prepared_case_sha256": sha256(canonical_bytes(source)).hexdigest(),
        "reference_identities": [
            {
                "ordinal": ref["reference_ordinal"],
                "original": ref["original_identity"],
                "verified": ref["verified_identity"],
            }
            for ref in case.references
        ],
    }


def _joins(case: PreparedCase) -> dict:
    references = []
    for ref in case.references:
        try:
            validate_verified_identity(ref["verified_identity"])
            reason = "complete_identity_only_no_persisted_row_binding"
        except ContractError as exc:
            reason = str(exc)
        references.append({"ordinal": ref["reference_ordinal"], "reason": reason})
    return {
        "reference_to_wave7": {
            "status": "NOT_CONNECTED",
            "reason": "no_complete_persisted_reference_binding",
            "references": references,
        },
        "preparation_to_review": {
            "status": "NOT_CONNECTED",
            "reason": "no_cross_dimension_transition_contract",
        },
        "owner_workflow": {"status": "NOT_CONNECTED", "contract": "NOT_SUPPLIED"},
    }


def _apply(record: DraftRecord | None, review: str, dimension: str, action: str):
    if record is None:
        raise BridgeError("bridge: no_draft_available")
    if dimension == "preparation":
        candidate = transition(
            record, action, expected_revision=record.current.number, **_ATTRIBUTION
        )
        build_history(candidate)
        return candidate, review
    return record, next_review_status(review, action).value


def _eligibility(record: DraftRecord | None, review: str) -> dict:
    result = {"meaning": "PURE_CONTRACT_ONLY", "preparation": [], "internal_review": []}
    for dimension, actions, field in (
        ("preparation", State, "preparation"),
        ("review", ReviewAction, "internal_review"),
    ):
        for action in actions:
            try:
                _apply(record, review, dimension, action.value)
            except (ValidationError, ContractError, BridgeError):
                continue
            result[field].append(action.value)
    return result


def _view(case, batch) -> dict:
    return {
        "schema": SCHEMA,
        "synthetic_fixtures_only": True,
        "contract_version": CONTRACT_VERSION,
        "source_identity": _identity(case, batch),
        "source": {
            "batch_raw_text": batch.raw_source,
            "row_text": case.raw_source,
            "row_kind": "serialized_parsed_fields",
            "row_start": case.source_start,
            "row_end": case.source_end,
            "references": list(case.references),
            "intake_state": case.intake_state,
            "issues": list(case.issues),
        },
        "initial": snapshot(case.record, "UNREVIEWED"),
        "review_origin": "SYNTHETIC_INITIAL_LABEL_NOT_PERSISTED",
        "eligibility": _eligibility(case.record, "UNREVIEWED"),
        "joins": _joins(case),
        "gates": {
            "B": "NOT_PASSED",
            "C": "HOLD",
            "D": "HOLD",
            "E": "HOLD",
            "Phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
            "U03/U10": "OWNER_APPROVAL_PENDING",
        },
    }


def inspect_case(case_key: str, *, synthetic_fixtures_only: bool = False) -> dict:
    """Detached identity, receipt snapshot and technical eligibility for a fixed row."""
    return json.loads(canonical_bytes(_view(*_select(case_key, synthetic_fixtures_only))))


def project(request: dict) -> dict:
    """Apply each source/state-pinned attempt to local immutable snapshots only.

    No idempotency ledger: repeating a successful command with its old token is
    rejected as stale. Invalid attempts change neither preparation nor review.
    Source tokens attest equality to fixed code-selected fixtures, not authenticity.
    """
    raw = _request_bytes(request)
    request = json.loads(raw)
    if (
        type(request) is not dict
        or set(request) != {"schema", "synthetic_fixtures_only", "case_key", "commands"}
        or request["schema"] != SCHEMA
        or request["synthetic_fixtures_only"] is not True
        or type(request["commands"]) is not list
        or len(request["commands"]) > MAX_COMMANDS
    ):
        raise BridgeError("bridge: invalid_envelope")
    case, batch = _select(request["case_key"], True)
    result = _view(case, batch)
    record, review = case.record, "UNREVIEWED"
    steps = []
    for ordinal, command in enumerate(request["commands"], 1):
        before = snapshot(record, review)
        accepted, disposition, reason = False, "REJECTED", "bridge: invalid_command"
        try:
            if (
                type(command) is not dict
                or set(command) != {"dimension", "action", "source_identity", "expected_state"}
                or any(
                    type(command[k]) is not str or not 1 <= len(command[k]) <= 100
                    for k in ("dimension", "action")
                )
            ):
                raise BridgeError(reason)
            if canonical_bytes(command["source_identity"]) != canonical_bytes(
                result["source_identity"]
            ):
                raise BridgeError("bridge: source_identity_mismatch")
            if canonical_bytes(command["expected_state"]) != canonical_bytes(state_token(before)):
                raise BridgeError("bridge: state_snapshot_mismatch")
            if command["dimension"] not in ("preparation", "review"):
                disposition = "NOT_CONNECTED"
                raise BridgeError("bridge: unsupported_dimension_join")
            record, review = _apply(record, review, command["dimension"], command["action"])
            accepted, disposition, reason = True, "PROJECTED", "accepted_by_pure_contract"
        except (ValidationError, ContractError, BridgeError) as exc:
            reason = str(exc)
        after = snapshot(record, review)
        steps.append(
            {
                "ordinal": ordinal,
                "command": command,
                "accepted": accepted,
                "disposition": disposition,
                "reason": reason,
                "before": before,
                "after": after,
                "before_sha256": state_token(before)["state_sha256"],
                "after_sha256": state_token(after)["state_sha256"],
                "state_changed": before != after,
                "eligibility_after": _eligibility(record, review),
            }
        )
    result.update(
        request_sha256=sha256(raw).hexdigest(),
        request_hash_kind="canonical_json",
        steps=steps,
        final=snapshot(record, review),
        final_eligibility=_eligibility(record, review),
    )
    return json.loads(canonical_bytes(result))


def scenario(case_key: str = "batch-synthetic-csv-1", *, synthetic_fixtures_only=False) -> dict:
    """Existing rehearsal attempts plus explicit missing-readiness/join/stale probes."""
    from apps.workflow_rehearsal.services import build_prepared_rehearsal

    view = inspect_case(case_key, synthetic_fixtures_only=synthetic_fixtures_only)
    rehearsal = build_prepared_rehearsal(case_key, synthetic_fixtures_only=True)
    attempts = [(step.dimension, step.action) for step in rehearsal.steps]
    attempts.extend(
        (("preparation", "ready_for_future_review"), ("preparation_to_review", "start_review"))
    )
    request = {
        "schema": SCHEMA,
        "synthetic_fixtures_only": True,
        "case_key": case_key,
        "commands": [],
    }
    state = view["initial"]
    for dimension, action in attempts:
        request["commands"].append(
            {
                "dimension": dimension,
                "action": action,
                "source_identity": view["source_identity"],
                "expected_state": state_token(state),
            }
        )
        state = project(request)["final"]
    # These probes retain well-formed commands but fail exact provenance/snapshot checks.
    stale = json.loads(canonical_bytes(request["commands"][1]))
    request["commands"].append(stale)
    wrong_source = json.loads(canonical_bytes(request["commands"][0]))
    wrong_source["source_identity"]["payload_sha256"] = "0" * 64
    request["commands"].append(wrong_source)
    return json.loads(canonical_bytes(request))
