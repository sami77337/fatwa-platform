"""Read-only, scoped projections; no shadow case state or permission grants."""

from apps.casework import services

FILTERS = {
    "all": "كل القضايا",
    "draft": "تحتاج إلى مسودة",
    "waiting": "بانتظار استيضاح",
    "review": "جاهزة للمراجعة",
    "returned": "أُعيدت للتعديل",
    "approved": "اكتملت المراجعة",
}
STAGES = {
    "RECEIVED": "سؤال جديد",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "بانتظار استيضاح",
    "RETURNED_FOR_CHANGES": "أُعيدت للتعديل",
    "ANSWERED": "اكتملت مراجعة الجواب",
}
EVENTS = {
    "INTAKE": "استلام السؤال الأصلي",
    "FOLLOWUP": "إضافة تعقيب وتحديث الوقائع",
    "SAVE_ANSWER": "حفظ إصدار جواب بشري",
    "CLARIFICATION": "طلب استيضاح",
    "APPROVE": "اعتماد إصدار الجواب",
    "RETURN_FOR_CHANGES": "إعادة الجواب للتعديل",
    "ROTATE_ACCESS": "تدوير وصول السائل",
    "REVOKE_ACCESS": "إبطال وصول السائل",
}


def describe(snapshot):
    latest = snapshot["answers"][-1] if snapshot["answers"] else None
    current = bool(latest and latest["evidence_version"] == snapshot["evidence_version"])
    stage = snapshot["status"]
    category = {
        "NEEDS_CLARIFICATION": "waiting",
        "RETURNED_FOR_CHANGES": "returned",
        "ANSWERED": "approved",
    }.get(stage, "review" if current else "draft")
    return {
        **snapshot,
        "stage_label": STAGES[stage],
        "category": category,
        "next_step": FILTERS[category],
        "latest_answer": latest,
        "stale_answer": bool(latest and not current),
        "can_review": category == "review",
    }


def read_workspace_case(**common):
    # The public read omits decision notes. Reuse its exact locked identity and
    # integrity boundary for this additional projection; never query by a naked ref.
    # Integration can promote this adapter into a public core read API later.
    with services._staff_case(
        common["case_id"], common["subject_id"], common["provider"],
        common["synthetic_fixtures_only"],
    ) as (case, _identity):
        snapshot = describe(services._staff(case))
        snapshot["timeline"] = [
            {
                "sequence": event.sequence,
                "label": EVENTS[event.action],
                "note": event.note,
                "answer_revision": event.answer_revision,
                "evidence_version": event.evidence_version,
            }
            for event in case.events.order_by("sequence")
        ]
        return snapshot


def queue(rows, selected_filter, query):
    # Search identifiers only: never reveal another case's question/answer as a snippet.
    described = [describe(row) for row in reversed(rows)]
    matched = [row for row in described if query.casefold() in row["public_ref"].casefold()]
    counts = {key: sum(key == "all" or row["category"] == key for row in matched)
              for key in FILTERS}
    return {
        "rows": [row for row in matched
                 if selected_filter == "all" or row["category"] == selected_filter],
        "filters": [{"key": key, "label": label, "count": counts[key]}
                    for key, label in FILTERS.items()],
        "selected_filter": selected_filter,
        "query": query,
        "total": len(described),
    }
