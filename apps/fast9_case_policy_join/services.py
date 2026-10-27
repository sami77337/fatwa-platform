"""Select exact synthetic evidence and recheck both identities after evaluation.

Receipts are unsigned comparison metadata, never capabilities. No caller source,
policy document, persisted case, role assignment or write operation is accepted.
"""

import json
import re
from dataclasses import asdict, dataclass, field, fields
from hashlib import sha256
from typing import Literal

from apps.fast8_case_permission import services as cases
from apps.permission_lab import services as lab
from apps.permission_lab.sources import SourceUnavailable
from apps.policy_gap_engine import evidence
from apps.policy_gap_engine import services as gap

SCHEMA = "fatwa.fast9.case-policy-join.v1"
MAX_RECEIPT_BYTES = 16384


class JoinError(ValueError):
    """Fixed diagnostic code; never caller content or filesystem details."""


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    actor: str
    action: str
    resource: str
    target_state: str | None
    record_category: str
    record_id: str
    document_id: str
    policy_token: str
    source_commit: str
    inventory_sha256: str
    evidence_sha256: str
    binding_scope: str = "SYNTHETIC_ID_MEMBERSHIP_ONLY"


@dataclass(frozen=True, slots=True)
class JoinReceipt:
    case: cases.CaseDescriptor
    scenario: ScenarioEvidence
    schema_version: str = SCHEMA


@dataclass(frozen=True, slots=True)
class JoinDecision:
    synthetic_context: Literal["VERIFIED", "REJECTED", "NOT_CONNECTED"]
    reason_codes: tuple[str, ...]
    receipt: JoinReceipt | None = None
    valid_combination: bool = False
    candidate_status: str = "NOT_EVALUATED"
    workflow_target: str | None = None
    effect: Literal["DENY"] = field(default="DENY", init=False)
    allowed: Literal[False] = field(default=False, init=False)
    policy_status: Literal["POLICY_PENDING"] = field(default="POLICY_PENDING", init=False)
    evidence_status: Literal["MISSING_EVIDENCE"] = field(default="MISSING_EVIDENCE", init=False)
    owner_policy_connection: Literal["NOT_CONNECTED"] = field(default="NOT_CONNECTED", init=False)
    persisted_case_connection: Literal["NOT_CONNECTED"] = field(default="NOT_CONNECTED", init=False)
    scenario_binding: str = field(default="EXPLICIT_HYPOTHESIS_NOT_CASE_POLICY", init=False)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise JoinError(code)


def _identifier(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,96}", value) is not None


def _request(case_key, actor, action, resource, target_state):
    _require(all(_identifier(v) for v in (case_key, actor, action, resource)), "INVALID_IDENTIFIER")
    _require(target_state is None or _identifier(target_state), "INVALID_IDENTIFIER")


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _scenario(actor: str, action: str, resource: str, target_state: str | None) -> ScenarioEvidence:
    inventory, report = evidence.load_evidence()
    catalog = lab.build_catalog()
    for identifiers in (catalog.actors, catalog.actions, tuple(r.id for r in catalog.resources)):
        _require(all(_identifier(v) for v in identifiers), "INVALID_SCENARIO_ID")
        _require(len(set(identifiers)) == len(identifiers), "DUPLICATE_SCENARIO_ID")
    _require(actor in catalog.actors, "UNKNOWN_ACTOR")
    _require(action in catalog.actions, "UNKNOWN_ACTION")
    _require(resource in {r.id for r in catalog.resources}, "UNKNOWN_RESOURCE")
    ids = [row["id"] for row in report["records"]]
    _require(all(_identifier(v) for v in ids), "INVALID_POLICY_ID")
    _require(len(ids) == len(set(ids)), "DUPLICATE_POLICY_ID")
    matches = [row for row in report["records"] if row["id"] == action]
    _require(len(matches) == 1, "SCENARIO_EVIDENCE_MISSING")
    row = matches[0]
    _require(
        report["status"] == "SYNTHETIC_ONLY"
        and report["provenance"]["hashes_verified"] is True
        and row["binding_scope"] == "SYNTHETIC_ID_MEMBERSHIP_ONLY",
        "SOURCE_CONTRACT_UNAVAILABLE",
    )
    return ScenarioEvidence(
        actor,
        action,
        resource,
        target_state,
        row["category"],
        row["source_ref"]["record_id"],
        row["source_ref"]["document_id"],
        row["policy_token"],
        catalog.source_commit,
        catalog.inventory_sha256,
        sha256(
            _canonical(
                {"inventory": inventory, "evidence": report, "catalog": asdict(catalog)}
            ).encode("utf-8")
        ).hexdigest(),
    )


def _snapshot(case_key, actor, action, resource, target_state) -> JoinReceipt:
    return JoinReceipt(
        cases.describe_case(case_key, scenario_resource=resource),
        _scenario(actor, action, resource, target_state),
    )


def select_evidence(
    *,
    case_key: object,
    actor: object,
    action: object,
    resource: object,
    target_state: object = None,
) -> JoinReceipt:
    """Select a real fixed queue row plus one pinned hypothetical policy record.

    Workflow-only compatibility without a policy record is explicitly unjoined.
    A valid candidate is still DENY, including MUFTI and peer-admin probes.
    """
    try:
        _request(case_key, actor, action, resource, target_state)
        before = _snapshot(case_key, actor, action, resource, target_state)
        decision = gap.evaluate(gap.CandidateRequest(actor, action, resource, target_state))
        _require(
            "SOURCE_CONTRACT_UNAVAILABLE" not in decision.reason_codes,
            "SOURCE_CONTRACT_UNAVAILABLE",
        )
        _require(decision.valid_combination, "INVALID_SCENARIO")
        _require(
            _snapshot(case_key, actor, action, resource, target_state) == before, "STALE_RECEIPT"
        )
        return before
    except cases.ContextError as exc:
        raise JoinError(str(exc)) from None
    except SourceUnavailable:
        raise JoinError("SOURCE_CONTRACT_UNAVAILABLE") from None


def parse_receipt(text: str) -> JoinReceipt:
    """Bounded strict JSON: no duplicate fields, extra grants, normalization or paths."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "INVALID_RECEIPT")
            result[key] = value
        return result

    try:
        _require(
            type(text) is str and len(text.encode("utf-8")) <= MAX_RECEIPT_BYTES, "INVALID_RECEIPT"
        )
        value = json.loads(text, object_pairs_hook=unique)
        _require(
            type(value) is dict and set(value) == {f.name for f in fields(JoinReceipt)},
            "INVALID_RECEIPT",
        )
        _require(value["schema_version"] == SCHEMA, "INVALID_RECEIPT")
        case = cases.parse_descriptor(_canonical(value["case"]))
        scenario = value["scenario"]
        _require(
            type(scenario) is dict and set(scenario) == {f.name for f in fields(ScenarioEvidence)},
            "INVALID_RECEIPT",
        )
        for key, item in scenario.items():
            if key == "target_state" and item is None:
                continue
            _require(type(item) is str and 0 < len(item) <= 256, "INVALID_RECEIPT")
        _request(
            case.case_key,
            scenario["actor"],
            scenario["action"],
            scenario["resource"],
            scenario["target_state"],
        )
        for key in ("inventory_sha256", "evidence_sha256"):
            _require(re.fullmatch("[0-9a-f]{64}", scenario[key]) is not None, "INVALID_RECEIPT")
        _require(scenario["resource"] == case.scenario_resource, "INVALID_RECEIPT")
        return JoinReceipt(case, ScenarioEvidence(**scenario))
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise JoinError("INVALID_RECEIPT") from None


def rejected(code: str) -> JoinDecision:
    status = (
        "NOT_CONNECTED"
        if code in {"QUEUE_UNAVAILABLE", "SOURCE_CONTRACT_UNAVAILABLE", "SCENARIO_EVIDENCE_MISSING"}
        else "REJECTED"
    )
    return JoinDecision(
        status, tuple(sorted({"DENY_DEFAULT", "POLICY_PENDING", "MISSING_EVIDENCE", code}))
    )


def evaluate_join(
    *,
    case_key: object,
    receipt: object,
    actor: object,
    action: object,
    resource: object,
    target_state: object = None,
) -> JoinDecision:
    """Revalidate case AND scenario receipt, delegate FAST8, then recheck BOTH.

    Caller request is independent from receipt. No supplied receipt is echoed on
    rejection; only a freshly verified snapshot may appear in diagnostics.
    """
    try:
        _request(case_key, actor, action, resource, target_state)
        _require(
            type(receipt) is JoinReceipt
            and type(receipt.case) is cases.CaseDescriptor
            and type(receipt.scenario) is ScenarioEvidence,
            "INVALID_RECEIPT",
        )
        checked = parse_receipt(_canonical(asdict(receipt)))
        _require(case_key == checked.case.case_key, "CROSS_CASE_SUBSTITUTION")
        _require(
            (actor, action, resource, target_state)
            == (
                checked.scenario.actor,
                checked.scenario.action,
                checked.scenario.resource,
                checked.scenario.target_state,
            ),
            "SCENARIO_SUBSTITUTION",
        )
        current = _snapshot(case_key, actor, action, resource, target_state)
        _require(current == checked, "STALE_RECEIPT")
        decision = cases.evaluate_case(
            case_key=case_key,
            descriptor=current.case,
            actor=actor,
            action=action,
            target_state=target_state,
        )
        after = _snapshot(case_key, actor, action, resource, target_state)
        _require(after == current, "STALE_RECEIPT")
        if decision.context_status != "VERIFIED":
            return JoinDecision(
                decision.context_status, tuple(sorted({*decision.reason_codes, "MISSING_EVIDENCE"}))
            )
        _require(decision.valid_combination, "INVALID_SCENARIO")
        return JoinDecision(
            "VERIFIED",
            tuple(sorted({*decision.reason_codes, "MISSING_EVIDENCE"})),
            current,
            True,
            decision.candidate_status,
            decision.workflow_target,
        )
    except cases.ContextError as exc:
        return rejected(str(exc))
    except SourceUnavailable:
        return rejected("SOURCE_CONTRACT_UNAVAILABLE")
    except JoinError as exc:
        return rejected(str(exc))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return rejected("INVALID_RECEIPT")


def report(decision: JoinDecision) -> dict:
    result = asdict(decision)
    result.update(
        scope="SYNTHETIC_DIAGNOSTICS_ONLY",
        active_grants=0,
        runtime_executable=False,
        gates={
            "gate_b": "NOT_PASSED",
            "gates_c_d_e": "HOLD",
            "phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
            "U03_U10": "OWNER_APPROVAL_PENDING",
        },
    )
    return result


def inspect_request(*, receipt_text: str | None = None, **request) -> JoinDecision:
    """Shared read-only adapter boundary; selection also returns an explicit DENY."""
    try:
        receipt = (
            select_evidence(**request) if receipt_text is None else parse_receipt(receipt_text)
        )
        return evaluate_join(receipt=receipt, **request)
    except JoinError as exc:
        return rejected(str(exc))
