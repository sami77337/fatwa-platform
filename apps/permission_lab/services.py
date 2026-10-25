"""Explain hypothetical DENY results. This module cannot authorize or dispatch.

Resources below are invented inspection contexts, not case IDs or model handles.
Candidate metadata and workflow validity are never permission grants.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from apps.intake_workflow.contracts import (
    ContractError,
    ReviewAction,
    ReviewStatus,
    next_review_status,
)

from .sources import INVENTORY_SHA256, SOURCE_COMMIT, load_inventory


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    label: str
    state: str = ""


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Decision:
    valid_combination: bool
    reasons: tuple[Reason, ...]
    candidate_roles: tuple[str, ...] = ()
    workflow_target: str | None = None
    effect: Literal["DENY"] = field(default="DENY", init=False)
    allowed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class Catalog:
    actors: tuple[str, ...]
    actions: tuple[str, ...]
    resources: tuple[Resource, ...]
    source_commit: str = SOURCE_COMMIT
    inventory_sha256: str = INVENTORY_SHA256


_RESOURCES = (
    Resource("synthetic::answer", "مسودة جواب اصطناعية", "SYNTHETIC_DRAFT"),
    Resource("synthetic::catalog", "فهرس اصطناعي"),
    Resource("synthetic::case", "سياق حالة اصطناعي"),
    Resource("synthetic::delivery", "سياق تسليم اصطناعي"),
    *(
        Resource("workflow::" + state, "سياق مراجعة اصطناعي: " + state, state)
        for state in ReviewStatus
    ),
)

# These exact bindings define test scenarios only. They are not historical RBAC
# mappings, policy acceptance or role grants. They never resolve persisted data.
_BINDINGS = {
    "synthetic::answer.create": "synthetic::answer",
    "synthetic::catalog.inspect": "synthetic::catalog",
    "P00-03::case.project": "synthetic::case",
    "P00-03::delivery.hold": "synthetic::delivery",
    "synthetic::answer.draft": "synthetic::answer",
}
_BASE_REASONS = (
    Reason("DENY_DEFAULT", "النتيجة الفعلية رفض افتراضي؛ المختبر لا يمنح أي صلاحية."),
    Reason("POLICY_PENDING", "سياسات U03/U10 بانتظار قبول المالك؛ التعليق يعني الرفض."),
    Reason(
        "HISTORICAL_INVENTORY_UNAVAILABLE",
        "صفوف الصلاحيات التاريخية الـ70 والانتقالات الـ58 غير متاحة؛ الفحص اصطناعي فقط.",
    ),
)


def _catalog(inventory: dict) -> Catalog:
    return Catalog(
        actors=tuple(inventory["policy"]["role_hierarchy"]),
        actions=(
            *(item["action_id"] for item in inventory["actions"]),
            *(item["transition_id"] for item in inventory["transitions"]),
            *(action.value for action in ReviewAction),
        ),
        resources=_RESOURCES,
    )


def build_catalog() -> Catalog:
    """Build from the pinned synthetic contract, failing closed if unavailable."""
    return _catalog(load_inventory())


def _identifier(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_:.\-]{1,96}", value) is not None


def evaluate(actor: object, action: object, resource: object) -> Decision:
    """Inspect an exact triple, with no normalization, inheritance or execution.

    valid_combination describes known identifiers and compatible resource/state,
    never authorization. The actor is a hypothetical label, not a session user.
    SourceUnavailable is a closed failure for the UI to report as DENY/503.
    """
    inventory = load_inventory()
    catalog = _catalog(inventory)
    reasons = list(_BASE_REASONS)
    if not all(_identifier(value) for value in (actor, action, resource)):
        return Decision(
            False,
            (
                *reasons,
                Reason(
                    "INVALID_IDENTIFIER",
                    "المعرّفات يجب أن تكون مطابقة تماماً؛ لا تُقبل البدائل أو المحارف الخفية.",
                ),
            ),
        )

    valid = True
    if actor not in catalog.actors:
        valid = False
        code = "INTERNAL_PRINCIPAL_FORBIDDEN" if actor == "DOMAIN_TRANSACTION" else "UNKNOWN_ACTOR"
        reasons.append(
            Reason(code, "الفاعل غير معرّف كدور؛ المعاملة الداخلية ليست فاعلاً قابلاً للتشغيل.")
        )
    if action not in catalog.actions:
        valid = False
        reasons.append(Reason("UNKNOWN_ACTION", "العملية غير موجودة في العقد الاصطناعي المثبت."))
    selected = next((item for item in catalog.resources if item.id == resource), None)
    if selected is None:
        valid = False
        reasons.append(Reason("UNKNOWN_RESOURCE", "المورد غير موجود؛ لا يتم تحميل أي حالة فعلية."))

    candidate_roles: tuple[str, ...] = ()
    target = None
    actions = {item["action_id"]: item for item in inventory["actions"]}
    transitions = {item["transition_id"]: item for item in inventory["transitions"]}
    transition = transitions.get(action)
    entry = actions.get(transition["action_id"] if transition else action)
    if entry is not None:
        candidate_roles = tuple(item["name"] for item in entry["candidate_principals"])
        reasons.append(Reason("CANDIDATE_ONLY", "ربط الأدوار مرشح توثيقي فقط؛ لا يفعّل الوصول."))
        if actor not in candidate_roles:
            reasons.append(
                Reason("ACTOR_NOT_CANDIDATE", "الدور ليس ضمن المرشحين للعملية في هذه العينة.")
            )
        if (
            entry["operation"] in {"SCHOLARLY_CREATE", "SCHOLARLY_APPROVE"}
            and actor not in inventory["policy"]["scholarly_authorities"]
        ):
            reasons.append(
                Reason(
                    "SCHOLARLY_AUTHORITY_RESTRICTED",
                    "التساوي الإداري لا يمنح اختصاصاً علمياً؛ الترشيح العلمي للمفتي فقط.",
                )
            )
        if entry["record_kind"] == "INTERNAL_ATOMIC_EFFECT":
            reasons.append(
                Reason("INTERNAL_EFFECT_ONLY", "أثر داخلي ذري غير قابل للاستدعاء المستقل.")
            )
        if _BINDINGS.get(action) != resource:
            valid = False
            reasons.append(
                Reason("ACTION_RESOURCE_MISMATCH", "العملية لا تطابق المورد الاصطناعي المحدد.")
            )
        elif transition:
            target = transition["to_state"]
        if transition:
            reasons.append(
                Reason("TRANSITION_DISABLED", "الانتقال موثق ومعطل؛ عرض وجهته لا ينفذه.")
            )
    elif action in ReviewAction:
        if selected is None or not selected.id.startswith("workflow::"):
            valid = False
            reasons.append(
                Reason(
                    "ACTION_RESOURCE_MISMATCH", "عملية المراجعة تتطلب سياق مراجعة اصطناعياً مطابقاً."
                )
            )
        else:
            try:
                target = next_review_status(selected.state, action).value
            except ContractError:
                valid = False
                reasons.append(
                    Reason(
                        "WORKFLOW_TRANSITION_INVALID", "العملية غير صالحة من حالة المراجعة المحددة."
                    )
                )
            else:
                reasons.append(
                    Reason(
                        "WORKFLOW_NOT_AUTHORIZATION",
                        "توافق انتقال المراجعة لا يثبت صلاحية؛ لا انتقال ولا كتابة في المختبر.",
                    )
                )
    return Decision(valid, tuple(reasons), candidate_roles, target)
