"""Native bounded dictionary forms, independent review and observational comparison."""

import uuid

from django.shortcuts import render

from apps.casework import services as cases
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm
from apps.delivery_queue.services import synthetic_queue_atomic

from . import governance, governance_pins, policy

ENTRY_FIELDS = {
    f"entry_{number}_{field}" for number in range(12) for field in ("key", "term", "alternatives")
}
MAPPING_FIELDS = {
    f"map_{number}_{field}" for number in range(12) for field in ("kind", "targets", "reason")
}
FIELDS = {
    "cs_dictionary_open": set(),
    "cs_dictionary_save": {"state", "title", "provenance"} | ENTRY_FIELDS | MAPPING_FIELDS,
    "cs_dictionary_preview": {"state", "queries"},
    "cs_dictionary_preview_open": {"state"},
    "cs_dictionary_review": {"state", "decision", "note", "ttl", "confirm"},
    "cs_dictionary_search": {"state", "query", "page"},
    "cs_shadow_run": {"state", "query"},
    "cs_shadow_read": {"state"},
}
STATE_FIELDS = {"binding", "case_ref", "revision", "evidence_version", "request_key", "purpose"}
MAPPING_LABELS = (
    ("SAME", "المعرف واللفظ مستمران"),
    ("RENAMED", "تغيير تسمية موضح"),
    ("MOVED", "نقل موضح"),
    ("SPLIT", "تقسيم إلى معرفات جديدة"),
    ("MERGED", "دمج في معرف جديد"),
    ("NO_EQUIVALENT", "لا مقابل في الإصدار الجديد"),
)
STATES = {
    "DRAFT": "بانتظار المعاينة والمراجعة",
    "APPROVE": "مراجع ومتاح حتى الموعد المحدد",
    "REJECT": "مرفوض",
    "RETIRE": "مسحوب من الاستخدام",
    "EXPIRED": "انتهت مدة المراجعة",
}


def _allowed(context, case, action):
    try:
        context.require(case, action)
    except cases.CaseConflict as exc:
        if str(exc) == "search_action_denied":
            return False
        raise
    return True


def _state(request, base, desk, purpose, **values):
    from . import views

    return views._state(
        request,
        base,
        {
            "case_ref": desk["case_ref"],
            "revision": desk["revision"],
            "evidence_version": desk["evidence_version"],
            "request_key": str(uuid.uuid4()),
            "purpose": purpose,
            **values,
        },
    )


def _read(request, base, fields, purpose, extra):
    from . import views

    state = views._read_state(request, base, fields)
    if set(state) != STATE_FIELDS | set(extra) or state["purpose"] != purpose:
        raise InvalidForm("search_governance_state_invalid")
    return state


def _source_forms(request, base, rows):
    from . import views

    for row in rows:
        row["state"] = views._state(
            request,
            base,
            {
                "case_ref": row.get("case_ref", base["case_ref"]),
                "generation_id": row["generation_id"],
                "document_id": row["document_id"],
            },
        )


def page(request, base, *, preview_id=None, searched=None, comparison_id=None, message=""):
    with policy.boundary(**base, action="DICTIONARY_READ") as context:
        case = context.cases[str(base["case_id"])]
        desk = governance.desk_in_context(context, case_id=base["case_id"])
        capabilities = {
            action: _allowed(context, case, action)
            for action in (
                "DICTIONARY_EDIT",
                "DICTIONARY_REVIEW",
                "DICTIONARY_USE",
                "SEARCH",
                "SHADOW",
                "SHADOW_READ",
            )
        }
        dictionaries = desk["dictionaries"]
        previous = dictionaries[0] if dictionaries else None
        entries = previous["entries"] if previous else []
        editing = [
            {
                "number": number,
                **(
                    entries[number]
                    if number < len(entries)
                    else {"key": "", "term": "", "alternatives": []}
                ),
            }
            for number in range(12)
        ]
        for row in editing:
            row["alternatives_text"] = "، ".join(row["alternatives"])
        for row in dictionaries:
            row["state_label"] = STATES[row["state"]]
            row["state_token"] = _state(
                request,
                base,
                desk,
                "dictionary",
                dictionary_id=row["id"],
                sequence=row["decision_sequence"],
                preview_id=row["latest_preview_id"],
            )
        preview = (
            governance.preview_in_context(context, case=case, preview_id=preview_id)
            if preview_id
            else None
        )
        result = (
            governance.search_in_context(
                context,
                case=case,
                revision_id=searched["revision_id"],
                value=searched["value"],
                page=searched["page"],
            )
            if searched
            else None
        )
        comparison = (
            governance.shadow_in_context(context, case=case, comparison_id=comparison_id)
            if comparison_id
            else None
        )
        if result:
            _source_forms(request, {**base, "case_ref": desk["case_ref"]}, result["results"])
            result["state_token"] = next(
                row["state_token"]
                for row in dictionaries
                if row["id"] == result["dictionary"]["id"]
            )
        if comparison:
            for summary in (comparison["baseline"], comparison["candidate"]):
                _source_forms(
                    request, {**base, "case_ref": desk["case_ref"]}, summary.get("rows", [])
                )
        history = (
            governance.shadow_history_in_context(context, case=case)
            if all(capabilities[action] for action in ("SHADOW_READ", "DICTIONARY_USE", "SEARCH"))
            else []
        )
        for row in history:
            row["state_token"] = _state(request, base, desk, "shadow", comparison_id=row["id"])
        create_state = _state(
            request,
            base,
            desk,
            "save",
            number=desk["number"],
            previous_keys=[row["key"] for row in entries],
        )
        return private(
            render(
                request,
                "canonical_search/governance.html",
                {
                    "desk": desk,
                    "create_state": create_state,
                    "editing": editing,
                    "mapping_labels": MAPPING_LABELS,
                    "previous": previous,
                    "preview": preview,
                    "result": result,
                    "comparison": comparison,
                    "history": history,
                    "capabilities": capabilities,
                    "message": message,
                },
            )
        )


def _entries(fields):
    result = []
    for number in range(12):
        key, term, alternatives = (
            fields[f"entry_{number}_{field}"] for field in ("key", "term", "alternatives")
        )
        if not any((key, term, alternatives)):
            continue
        if not all((key, term, alternatives)):
            raise InvalidForm("search_dictionary_incomplete_row")
        result.append(
            {
                "key": key,
                "term": term,
                "alternatives": [
                    value.strip() for value in alternatives.replace("،", ",").split(",")
                ],
            }
        )
    return result


def _mapping(fields, keys):
    result = []
    for number in range(12):
        kind, targets, reason = (
            fields[f"map_{number}_{field}"] for field in ("kind", "targets", "reason")
        )
        if number >= len(keys):
            if any((kind, targets, reason)):
                raise InvalidForm("search_dictionary_extra_mapping")
            continue
        result.append(
            {
                "from": keys[number],
                "kind": kind,
                "to": [value.strip() for value in targets.replace("،", ",").split(",")]
                if targets
                else [],
                "reason": reason,
            }
        )
    return result


def handle(request, base, action, fields):
    governance_pins.enabled()
    if action == "cs_dictionary_open":
        return page(request, base)
    if action == "cs_shadow_read":
        state = _read(request, base, fields, "shadow", {"comparison_id"})
        return page(request, base, comparison_id=state["comparison_id"])
    if action == "cs_dictionary_save":
        state = _read(request, base, fields, "save", {"number", "previous_keys"})
        with synthetic_queue_atomic():
            governance.create_revision(
                **base,
                expected_revision=state["revision"],
                expected_evidence_version=state["evidence_version"],
                expected_number=state["number"],
                request_key=state["request_key"],
                title=fields["title"],
                provenance=fields["provenance"],
                entries=_entries(fields),
                mapping=_mapping(fields, state["previous_keys"]),
            )
            return page(
                request,
                base,
                message="حُفظ إصدار مستقل. يلزم فحص أثره ومراجعته قبل استخدامه في البحث.",
            )
    state = _read(request, base, fields, "dictionary", {"dictionary_id", "sequence", "preview_id"})
    pins = {
        "expected_revision": state["revision"],
        "expected_evidence_version": state["evidence_version"],
        "request_key": state["request_key"],
    }
    if action == "cs_dictionary_search":
        if not fields["page"].isascii() or not fields["page"].isdigit():
            raise InvalidForm("search_dictionary_page_invalid")
        return page(
            request,
            base,
            searched={
                "revision_id": state["dictionary_id"],
                "value": fields["query"],
                "page": int(fields["page"]),
            },
        )
    if action == "cs_dictionary_preview_open":
        return page(request, base, preview_id=state["preview_id"])
    with synthetic_queue_atomic():
        if action == "cs_dictionary_preview":
            preview = governance.prepare_preview(
                **base,
                **pins,
                revision_id=state["dictionary_id"],
                queries=fields["queries"].splitlines(),
            )
            return page(
                request,
                base,
                preview_id=preview["id"],
                message="حُسب الأثر على الفهرس الحالي. هذه المعاينة لا تعتمد القاموس.",
            )
        if action == "cs_shadow_run":
            observation = governance.run_shadow(
                **base, **pins, revision_id=state["dictionary_id"], value=fields["query"]
            )
            return page(
                request,
                base,
                comparison_id=observation["comparison"]["id"],
                message="اكتملت المقارنة؛ بقيت نتائج البحث الأساسي كما هي.",
            )
        if action == "cs_dictionary_review":
            if (
                fields["confirm"] != "yes"
                or not fields["ttl"].isascii()
                or not fields["ttl"].isdigit()
            ):
                raise InvalidForm("search_dictionary_review_invalid")
            governance.decide(
                **base,
                **pins,
                revision_id=state["dictionary_id"],
                preview_id=None if fields["decision"] == "RETIRE" else state["preview_id"],
                expected_sequence=state["sequence"],
                action=fields["decision"],
                note=fields["note"],
                ttl_minutes=int(fields["ttl"]),
                confirmed=True,
            )
            return page(
                request, base, message="حُفظ قرار المراجعة مع هوية صاحبه وإصدار القاموس والمعاينة."
            )
    raise InvalidForm("search_governance_action_invalid")
