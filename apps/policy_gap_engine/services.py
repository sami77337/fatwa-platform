"""Deterministic deny-default policy gap evaluation, independent of Django and I/O writes."""

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Literal

from apps.intake_workflow.contracts import ReviewAction
from apps.permission_lab import services as lab
from apps.permission_lab import sources

from .evidence import _empty_evidence, inspect_evidence, load_evidence

__all__ = [
    "CandidateRequest",
    "GapDecision",
    "evaluate",
    "inspect_evidence",
    "build_report",
    "canonical_json",
]


@dataclass(frozen=True, slots=True)
class CandidateRequest:
    actor: object
    action: object
    resource: object
    target_state: object = None


@dataclass(frozen=True, slots=True)
class GapDecision:
    valid_combination: bool
    candidate_status: Literal["CANDIDATE_ONLY", "NOT_CANDIDATE", "EVIDENCE_MISSING", "INVALID"]
    reasons: tuple[lab.Reason, ...]
    candidate_roles: tuple[str, ...] = ()
    workflow_target: str | None = None
    effect: Literal["DENY"] = field(default="DENY", init=False)
    allowed: Literal[False] = field(default=False, init=False)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in self.reasons)


_EXTRA_REASONS = {
    "EVIDENCE_MISSING": "الأدلة التاريخية وبنود السياسات التفصيلية وقبول المالك غير متاحة.",
    "REQUEST_POLICY_EVIDENCE_MISSING": "توافق سير المراجعة لا يحدد مرشحي الصلاحية لهذا الطلب.",
    "TRANSITION_UNAUTHORIZED": "الانتقال مرفوض؛ فحص حالته لا يمنح إذناً ولا ينفذ تغييراً.",
    "TRANSITION_TARGET_MISMATCH": "الحالة المطلوبة لا تطابق وجهة الانتقال الموثقة.",
    "NOT_A_TRANSITION": "العملية المحددة ليست انتقالاً موثقاً.",
    "INVALID_IDENTIFIER": "يجب استخدام المعرّفات المطابقة تماماً دون تحويل أو تطبيع.",
    "SOURCE_CONTRACT_UNAVAILABLE": "تعذر التحقق من مصادر العينة المثبتة؛ لا توجد تغطية متحققة.",
    "DENY_DEFAULT": "النتيجة رفض افتراضي؛ محرك الفجوات لا يمنح أي صلاحية.",
    "POLICY_PENDING": "سياسات U03/U10 بانتظار قبول المالك؛ التعليق يعني الرفض.",
}


def _reasons(original: tuple[lab.Reason, ...], *codes: str) -> tuple[lab.Reason, ...]:
    by_code = {reason.code: reason for reason in original}
    for code in codes:
        by_code.setdefault(code, lab.Reason(code, _EXTRA_REASONS[code]))
    return tuple(by_code[code] for code in sorted(by_code))


def _unavailable_decision() -> GapDecision:
    return GapDecision(
        False,
        "EVIDENCE_MISSING",
        _reasons(
            (), "DENY_DEFAULT", "POLICY_PENDING", "EVIDENCE_MISSING", "SOURCE_CONTRACT_UNAVAILABLE"
        ),
    )


def _identifier(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,96}", value) is not None


def _evaluate(request: CandidateRequest, inventory: dict) -> GapDecision:
    base = lab.evaluate(request.actor, request.action, request.resource)
    codes = ["EVIDENCE_MISSING"]
    valid = base.valid_combination
    # Do not hash or compare untrusted objects before exact identifier validation.
    safe_action = request.action if _identifier(request.action) else None
    transition_ids = {row["transition_id"] for row in inventory["transitions"]}
    workflow_action = safe_action in {action.value for action in ReviewAction}
    is_transition = workflow_action or safe_action in transition_ids
    if is_transition:
        codes.append("TRANSITION_UNAUTHORIZED")
    if workflow_action:
        codes.append("REQUEST_POLICY_EVIDENCE_MISSING")
    if request.target_state is not None:
        if not _identifier(request.target_state):
            codes.append("INVALID_IDENTIFIER")
            valid = False
        elif not is_transition:
            codes.append("NOT_A_TRANSITION")
            valid = False
        elif request.target_state != base.workflow_target:
            codes.append("TRANSITION_TARGET_MISMATCH")
            valid = False
    if not valid:
        candidate = "INVALID"
    elif workflow_action:
        candidate = "EVIDENCE_MISSING"
    elif request.actor in base.candidate_roles:
        candidate = "CANDIDATE_ONLY"
    else:
        candidate = "NOT_CANDIDATE"
    return GapDecision(
        valid, candidate, _reasons(base.reasons, *codes), base.candidate_roles, base.workflow_target
    )


def evaluate(request: CandidateRequest) -> GapDecision:
    """Validate a hypothetical candidate. No authorization or state mutation exists."""
    if type(request) is not CandidateRequest:
        return GapDecision(
            False,
            "INVALID",
            _reasons(
                (), "DENY_DEFAULT", "POLICY_PENDING", "EVIDENCE_MISSING", "INVALID_IDENTIFIER"
            ),
        )
    try:
        inventory, _ = load_evidence()
        return _evaluate(request, inventory)
    except sources.SourceUnavailable:
        return _unavailable_decision()


def _negative_cases() -> tuple[tuple[str, CandidateRequest, str], ...]:
    return (
        (
            "candidate_pending",
            CandidateRequest("MUFTI", "synthetic::answer.create", "synthetic::answer"),
            "POLICY_PENDING",
        ),
        (
            "admin_peer_escalation",
            CandidateRequest("ORGANIZER_ADMIN", "synthetic::answer.create", "synthetic::answer"),
            "SCHOLARLY_AUTHORITY_RESTRICTED",
        ),
        (
            "lower_role_escalation",
            CandidateRequest("ORGANIZER", "synthetic::answer.create", "synthetic::answer"),
            "ACTOR_NOT_CANDIDATE",
        ),
        (
            "internal_principal",
            CandidateRequest("DOMAIN_TRANSACTION", "P00-03::case.project", "synthetic::case"),
            "INTERNAL_PRINCIPAL_FORBIDDEN",
        ),
        (
            "internal_effect",
            CandidateRequest("MUFTI", "P00-03::delivery.hold", "synthetic::delivery"),
            "INTERNAL_EFFECT_ONLY",
        ),
        (
            "cross_resource",
            CandidateRequest("MUFTI", "synthetic::answer.create", "synthetic::catalog"),
            "ACTION_RESOURCE_MISMATCH",
        ),
        (
            "wildcard",
            CandidateRequest("*", "synthetic::answer.create", "synthetic::answer"),
            "INVALID_IDENTIFIER",
        ),
        (
            "hidden_character",
            CandidateRequest("MUFTI\u200b", "synthetic::answer.create", "synthetic::answer"),
            "INVALID_IDENTIFIER",
        ),
        (
            "unknown_actor",
            CandidateRequest("SUPERUSER", "synthetic::answer.create", "synthetic::answer"),
            "UNKNOWN_ACTOR",
        ),
        (
            "unknown_action",
            CandidateRequest("MUFTI", "approve", "synthetic::answer"),
            "UNKNOWN_ACTION",
        ),
        (
            "unknown_resource",
            CandidateRequest("MUFTI", "synthetic::answer.create", "synthetic::unknown"),
            "UNKNOWN_RESOURCE",
        ),
        (
            "disabled_transition",
            CandidateRequest("MUFTI", "synthetic::answer.draft", "synthetic::answer"),
            "TRANSITION_DISABLED",
        ),
        (
            "wrong_target",
            CandidateRequest("MUFTI", "synthetic::answer.draft", "synthetic::answer", "PUBLISHED"),
            "TRANSITION_TARGET_MISMATCH",
        ),
        (
            "invalid_workflow_edge",
            CandidateRequest("MUFTI", "complete_review", "workflow::UNREVIEWED"),
            "WORKFLOW_TRANSITION_INVALID",
        ),
        (
            "compatible_is_not_authorized",
            CandidateRequest("MUFTI", "start_review", "workflow::UNREVIEWED"),
            "TRANSITION_UNAUTHORIZED",
        ),
    )


def _adversarial_checks(inventory: dict) -> dict:
    from apps.permission_lab.upstream import validator

    results = []
    for case_id, request, expected in _negative_cases():
        decision = _evaluate(request, inventory)
        results.append(
            {
                "id": case_id,
                "kind": "REQUEST",
                "expected_reason": expected,
                "observed_reasons": list(decision.reason_codes),
                "passed": decision.effect == "DENY"
                and decision.allowed is False
                and expected in decision.reason_codes,
            }
        )
    # Mutate only fresh in-memory copies for validation, never the trusted adapter.
    probes = (
        ("shadow_grant", "actions", 2, "grant_effect", "ALLOW"),
        ("extra_allow", "actions", 2, "allow", True),
        (
            "wildcard_candidate",
            "actions",
            2,
            "candidate_principals",
            [{"kind": "ROLE", "name": "*"}],
        ),
        ("callable_action", "actions", 2, "callable", True),
        ("enabled_transition", "transitions", 0, "enabled", True),
        ("invented_acceptance", "policy", None, "owner_approval", "APPROVED"),
        ("wrong_policy_source", "actions", 2, "policy_token", "APPROVED"),
        (
            "unknown_provenance",
            "actions",
            2,
            "source_ref",
            {"document_id": "not-supplied", "record_id": "synthetic::answer.create"},
        ),
    )
    for case_id, category, index, key, value in probes:
        mutated = deepcopy(inventory)
        target = mutated[category] if index is None else mutated[category][index]
        target[key] = value
        issues = validator.inspect_structure(mutated, synthetic=True)
        results.append(
            {
                "id": case_id,
                "kind": "INVENTORY_MUTATION",
                "observed_reasons": sorted({issue["code"] for issue in issues}),
                "passed": bool(issues),
            }
        )
    failed = sum(not result["passed"] for result in results)
    return {
        "status": "FAIL" if failed else "PASS",
        "evaluated": len(results),
        "failed": failed,
        "checks": results,
    }


def _request_report(request: CandidateRequest, decision: GapDecision, catalog: lab.Catalog) -> dict:
    """Echo known synthetic IDs only, never unknown caller data or object reprs."""

    def known(value: object, choices: tuple[str, ...]) -> str | None:
        return value if type(value) is str and value in choices else None

    result = asdict(decision)
    result["reason_codes"] = list(decision.reason_codes)
    result["request"] = {
        "actor": known(request.actor, catalog.actors),
        "action": known(request.action, catalog.actions),
        "resource": known(request.resource, tuple(item.id for item in catalog.resources)),
        "target_state_supplied": request.target_state is not None,
        "target_state_matches": request.target_state is not None
        and _identifier(request.target_state)
        and request.target_state == decision.workflow_target,
    }
    return result


def build_report(requests: tuple[CandidateRequest, ...] | None = None) -> dict:
    """Build a bounded offline report; PASS refers only to synthetic negative checks.

    Input is an explicit tuple of at most 256 candidate requests, not a policy
    document. Invalid service envelopes raise ValueError before any file access.
    """
    if requests is not None and (
        type(requests) is not tuple
        or not 1 <= len(requests) <= 256
        or any(type(item) is not CandidateRequest for item in requests)
    ):
        raise ValueError("INVALID_REQUEST_ENVELOPE")
    report = {
        "report_version": "fatwa.policy-gap.v1",
        "status": "EVIDENCE_UNAVAILABLE",
        "effect": "DENY",
        "allowed": False,
        "active_grants": 0,
        "runtime_executable": False,
        "scope": "SYNTHETIC_DIAGNOSTICS_ONLY",
        "gates": {
            "gate_b": "NOT_PASSED",
            "gates_c_d_e": "HOLD",
            "phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
        },
        "reason_codes": ["DENY_DEFAULT", "EVIDENCE_MISSING", "POLICY_PENDING"],
        "evidence": _empty_evidence(),
        "resources": [],
        "requests": [],
        "adversarial_checks": {"status": "NOT_RUN", "evaluated": 0, "failed": 0, "checks": []},
    }
    try:
        inventory, evidence = load_evidence()
        catalog = lab.build_catalog()
        chosen = requests if requests is not None else tuple(case[1] for case in _negative_cases())
        decisions = [
            _request_report(request, _evaluate(request, inventory), catalog) for request in chosen
        ]
        adversarial = _adversarial_checks(inventory)
        # Recheck after evaluation so a removed/changed bundle cannot leave a
        # partially verified report. No environment, clock, Git or network inputs.
        load_evidence()
    except sources.SourceUnavailable:
        report["reason_codes"].append("SOURCE_CONTRACT_UNAVAILABLE")
        return report
    report.update(
        status="SYNTHETIC_EVALUATED",
        evidence=evidence,
        requests=decisions,
        resources=[asdict(resource) for resource in catalog.resources],
        adversarial_checks=adversarial,
    )
    return report


def canonical_json(report: dict) -> str:
    """Stable UTF-8-ready serialization without Arabic normalization or timestamps."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
