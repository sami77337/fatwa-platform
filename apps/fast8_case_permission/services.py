"""Bind a hypothetical DENY decision to a fresh, exact editorial queue row.

Only built-in synthetic services are sources. A scenario resource is explicitly
chosen from permission_lab, never inferred from editorial status or permissions.
Descriptors are comparison receipts, not signed capabilities or authorization.
"""

import json
import re
from dataclasses import asdict, dataclass, field, fields
from hashlib import sha256
from typing import Literal

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.editorial_queue import services as queue
from apps.editorial_workbench.batches import PreparedCase
from apps.fatwa_drafts.intake import serialize_intake
from apps.intake_workflow import fixtures
from apps.permission_lab import services as lab
from apps.permission_lab.sources import SourceUnavailable
from apps.policy_gap_engine import services as gap

SCHEMA_VERSION = "fatwa.fast8.case-permission.v1"
MAX_DESCRIPTOR_BYTES = 8192


class ContextError(ValueError):
    """Fixed diagnostic code only; never contains caller content or source paths."""


@dataclass(frozen=True, slots=True)
class CaseDescriptor:
    case_key: str
    batch_id: str
    external_id: str
    payload_sha256: str
    source_sha256: str
    row_sha256: str
    source_kind: str
    source_start: int | None
    source_end: int | None
    row_ordinal: int | None
    fixture_label: str
    scenario_resource: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CaseDecision:
    context_status: Literal["VERIFIED", "REJECTED", "NOT_CONNECTED"]
    reason_codes: tuple[str, ...]
    descriptor: CaseDescriptor | None = None
    valid_combination: bool = False
    candidate_status: str = "NOT_EVALUATED"
    workflow_target: str | None = None
    effect: Literal["DENY"] = field(default="DENY", init=False)
    allowed: Literal[False] = field(default=False, init=False)
    policy_status: Literal["POLICY_PENDING"] = field(default="POLICY_PENDING", init=False)
    evidence_status: Literal["MISSING_EVIDENCE"] = field(default="MISSING_EVIDENCE", init=False)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContextError(code)


def _identifier(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,96}", value) is not None


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _shape(descriptor: object) -> None:
    _require(type(descriptor) is CaseDescriptor, "INVALID_DESCRIPTOR")
    for item in fields(CaseDescriptor):
        value = getattr(descriptor, item.name)
        if item.name in {"source_start", "source_end", "row_ordinal"}:
            _require(
                value is None or (type(value) is int and 0 <= value < 2**53), "INVALID_DESCRIPTOR"
            )
        else:
            _require(type(value) is str and 0 < len(value) <= 512, "INVALID_DESCRIPTOR")
    _require(descriptor.schema_version == SCHEMA_VERSION, "INVALID_DESCRIPTOR")
    for name in ("case_key", "batch_id", "external_id", "scenario_resource"):
        _require(_identifier(getattr(descriptor, name)), "INVALID_DESCRIPTOR")
    for name in ("payload_sha256", "source_sha256", "row_sha256"):
        _require(
            re.fullmatch(r"[0-9a-f]{64}", getattr(descriptor, name)) is not None,
            "INVALID_DESCRIPTOR",
        )


def parse_descriptor(text: str) -> CaseDescriptor:
    """Parse bounded metadata only, rejecting duplicate JSON keys and extra grants."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "INVALID_DESCRIPTOR")
            result[key] = value
        return result

    try:
        _require(
            type(text) is str and len(text.encode("utf-8")) <= MAX_DESCRIPTOR_BYTES,
            "INVALID_DESCRIPTOR",
        )
        value = json.loads(text, object_pairs_hook=unique)
        _require(
            type(value) is dict and set(value) == {f.name for f in fields(CaseDescriptor)},
            "INVALID_DESCRIPTOR",
        )
        descriptor = CaseDescriptor(**value)
        _shape(descriptor)
        return descriptor
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ContextError("INVALID_DESCRIPTOR") from exc


def _describe(case_key: object, scenario_resource: object) -> CaseDescriptor:
    _require(_identifier(case_key), "INVALID_CASE_KEY")
    _require(_identifier(scenario_resource), "INVALID_SCENARIO_RESOURCE")
    catalog = queue.build_queue_catalog()
    _require(len({row.case.key for row in catalog.rows}) == len(catalog.rows), "DUPLICATE_CASE_KEY")
    _require(
        len({batch.batch_id for batch in catalog.batches}) == len(catalog.batches),
        "DUPLICATE_BATCH_ID",
    )
    row = queue.select_queue(catalog.rows, key=case_key).selected
    _require(row is not None, "UNKNOWN_CASE_KEY")
    case = row.case
    _require(_identifier(case.external_id), "MISSING_OR_INVALID_EXTERNAL_ID")
    _require(
        sum(other.case.external_id == case.external_id for other in catalog.rows) == 1,
        "DUPLICATE_EXTERNAL_ID",
    )
    _require(case.status != "blocked", "ROW_BLOCKED")
    batch = next((item for item in catalog.batches if item.batch_id == row.batch_id), None)
    _require(batch is not None, "BATCH_IDENTITY_MISMATCH")
    raw_row = case.raw_source.encode("utf-8")
    _require(row.source_sha256 == _digest(raw_row), "SOURCE_SHA_MISMATCH")

    if type(case) is PreparedCase:
        _require(
            case.batch_id == row.batch_id and batch.source is not None, "BATCH_IDENTITY_MISMATCH"
        )
        source = batch.source
        _require(
            source.batch_id == row.batch_id and source.error_code is None, "BATCH_IDENTITY_MISMATCH"
        )
        payload = source.raw_source.encode("utf-8")
        _require(
            _digest(payload) == source.input_sha256 == case.payload_sha256, "PAYLOAD_SHA_MISMATCH"
        )
        _require(
            type(case.row_ordinal) is int and 1 <= case.row_ordinal <= source.record_count,
            "ROW_IDENTITY_MISMATCH",
        )
        _require(case.key == f"batch-{row.batch_id}-{case.row_ordinal}", "ROW_IDENTITY_MISMATCH")
        _require(case.source_start is None and case.source_end is None, "ROW_IDENTITY_MISMATCH")
        source_kind, ordinal = "PARSED_FIELDS_SERIALIZATION", case.row_ordinal
    else:
        _require(
            row.batch_id == queue.ORIGINAL_BATCH and batch.source is None, "BATCH_IDENTITY_MISMATCH"
        )
        if case.key == "history":
            payload = serialize_intake((REVISION_HISTORY_RECORD.intake,))
            _require(
                raw_row == payload and case.source_start is None and case.source_end is None,
                "ROW_IDENTITY_MISMATCH",
            )
            source_kind, ordinal = "SERIALIZED_HISTORY_INTAKE", None
        else:
            match = re.fullmatch(r"intake-([1-9][0-9]*)", case.key)
            _require(match is not None, "ROW_IDENTITY_MISMATCH")
            ordinal = int(match[1])
            payload = fixtures.synthetic_payload()
            start, end = case.source_start, case.source_end
            _require(
                type(start) is int and type(end) is int and 0 <= start < end <= len(payload),
                "ROW_IDENTITY_MISMATCH",
            )
            _require(payload[start:end] == raw_row, "ROW_IDENTITY_MISMATCH")
            source_kind = "ORIGINAL_UTF8_SLICE"
        _require(_digest(payload) == case.payload_sha256, "PAYLOAD_SHA_MISMATCH")

    descriptor = CaseDescriptor(
        case.key,
        row.batch_id,
        case.external_id,
        case.payload_sha256,
        row.source_sha256,
        _digest(_json_bytes(asdict(row))),
        source_kind,
        case.source_start,
        case.source_end,
        ordinal,
        case.fixture_label,
        scenario_resource,
    )
    _shape(descriptor)
    return descriptor


def describe_case(
    case_key: object, *, scenario_resource: object = "synthetic::case"
) -> CaseDescriptor:
    """Issue an immutable receipt from fixed synthetic sources only; no custom catalog."""
    try:
        descriptor = _describe(case_key, scenario_resource)
        _require(
            scenario_resource in {item.id for item in lab.build_catalog().resources},
            "INVALID_SCENARIO_RESOURCE",
        )
        return descriptor
    except queue.WorkbenchDataError as exc:
        raise ContextError("QUEUE_UNAVAILABLE") from exc
    except SourceUnavailable as exc:
        raise ContextError("SOURCE_CONTRACT_UNAVAILABLE") from exc


def rejected_decision(code: str) -> CaseDecision:
    """Construct a closed diagnostic; callers pass fixed adapter codes only."""
    return CaseDecision(
        "NOT_CONNECTED"
        if code in {"QUEUE_UNAVAILABLE", "SOURCE_CONTRACT_UNAVAILABLE"}
        else "REJECTED",
        tuple(sorted({"DENY_DEFAULT", "POLICY_PENDING", "MISSING_EVIDENCE", code})),
    )


def evaluate_case(
    *,
    case_key: object,
    descriptor: object,
    actor: object,
    action: object,
    target_state: object = None,
) -> CaseDecision:
    """Recheck the receipt, then delegate policy diagnostics; never authorize/write.

    Explicit case_key is independent of the receipt, preventing another case's
    complete receipt from being silently substituted. Revalidation also catches
    changes in revisions, timestamps, source slices and nested row diagnostics.
    """
    try:
        _shape(descriptor)
        _require(_identifier(case_key), "INVALID_CASE_KEY")
        _require(case_key == descriptor.case_key, "CROSS_CASE_SUBSTITUTION")
        current = describe_case(case_key, scenario_resource=descriptor.scenario_resource)
        _require(current == descriptor, "STALE_DESCRIPTOR")
        decision = gap.evaluate(
            gap.CandidateRequest(actor, action, descriptor.scenario_resource, target_state)
        )
        if "SOURCE_CONTRACT_UNAVAILABLE" in decision.reason_codes:
            return rejected_decision("SOURCE_CONTRACT_UNAVAILABLE")
        # A changed source during policy inspection cannot leave verified context.
        _require(
            describe_case(case_key, scenario_resource=descriptor.scenario_resource) == current,
            "STALE_DESCRIPTOR",
        )
        return CaseDecision(
            "VERIFIED",
            tuple(sorted({*decision.reason_codes, "MISSING_EVIDENCE"})),
            current,
            decision.valid_combination,
            decision.candidate_status,
            decision.workflow_target,
        )
    except ContextError as exc:
        return rejected_decision(str(exc))
