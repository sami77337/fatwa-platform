"""Read-only, scoped projections; no shadow case state or permission grants."""

from apps.casework import services
from apps.platform_recovery.integration import mutation_service

SORTS = {
    "newest": "الأحدث أولًا",
    "oldest": "الأقدم أولًا",
    "priority": "الأولوية العملية",
}
PRIORITY = {"returned": 0, "draft": 1, "review": 2, "waiting": 3, "approved": 4}
INBOXES = {
    "all": "كل العمل المخوّل",
    "mine": "قضاياي ومشاركاتي",
    "shared": "القضايا المشتركة غير المعينة",
    "followups": "تعقيبات بعد آخر جواب",
    "drafts": "المسودات المحفوظة",
    "review": "تحتاج إلى مراجعتي",
    "approved": "الأجوبة المعتمدة",
}


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
NEXT_STEPS = {
    "draft": "راجع الوقائع ثم حرر مسودة",
    "waiting": "بانتظار رد السائل على الاستيضاح",
    "review": "راجع أحدث مسودة واتخذ القرار",
    "returned": "راجع سبب الإعادة وعدّل المسودة",
    "approved": "راجع التسليم المستقل؛ الاعتماد لا يثبت الوصول",
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
        "next_step": NEXT_STEPS[category],
        "latest_answer": latest,
        "stale_answer": bool(latest and not current),
        "can_review": category == "review",
    }


@mutation_service
def read_workspace_case(*, include_answer_manifest=True, **common):
    # The public read omits decision notes. Reuse its exact locked identity and
    # integrity boundary for this additional projection; never query by a naked ref.
    # Integration can promote this adapter into a public core read API later.
    with services._staff_case(
        common["case_id"],
        common["subject_id"],
        common["provider"],
        common["synthetic_fixtures_only"],
    ) as (case, _identity):
        snapshot = describe(services._staff(case))
        latest = case.answers.order_by("-revision").first()
        snapshot["answer_manifest"] = (
            services._answer_manifest(latest) if include_answer_manifest else None
        )
        evidence = {item.version: item.text for item in case.evidence.all()}
        snapshot["timeline"] = [
            {
                "sequence": event.sequence,
                "label": EVENTS[event.action],
                "note": event.note,
                "answer_revision": event.answer_revision,
                "evidence_version": event.evidence_version,
                "created_at": event.created_at,
                "text": (
                    evidence[event.evidence_version]
                    if event.action in {"INTAKE", "FOLLOWUP"}
                    else event.answer.text
                    if event.action == "SAVE_ANSWER"
                    else ""
                ),
            }
            for event in case.events.select_related("answer").order_by("sequence")
        ]
        return snapshot


def _inbox_matches(row, inbox):
    latest = row["latest_answer"]
    if inbox == "mine":
        return bool(row.get("assignment", {}).get("is_mine"))
    if inbox == "shared":
        return bool(row.get("assignment", {}).get("is_shared"))
    if inbox == "followups":
        return row["evidence_version"] > (latest["evidence_version"] if latest else 1)
    if inbox == "drafts":
        return bool(latest and latest["id"] != row["approved_answer_id"])
    if inbox in {"review", "approved"}:
        return row["category"] == inbox
    return inbox == "all"


def queue(rows, selected_filter, query, sort="newest", inbox="all", assignments_enabled=False):
    # list_cases has already revalidated every case against the current scoped
    # identity. For a nonempty query it also requires separate CASE/source SEARCH
    # and omits answers/evidence without exact SEARCH grants before this haystack.
    # Keep result cards free of snippets.
    described = [describe(row) for row in reversed(rows)]
    needle = query.strip().casefold()
    matched = [
        row
        for row in described
        if any(
            needle in text.casefold()
            for text in (
                row["public_ref"],
                row["original_question"],
                *(item["text"] for item in row["followups"]),
                *(item["text"] for item in row["answers"]),
                *row["clarifications"],
            )
        )
    ]
    # Counts describe the complete authorized inbox, not the current search
    # subset. This keeps workload totals stable while the operator narrows results.
    counts = {
        key: (len(described) if key == "all" else sum(row["category"] == key for row in described))
        for key in FILTERS
    }
    visible = [row for row in matched if _inbox_matches(row, inbox)
               and (selected_filter == "all" or row["category"] == selected_filter)]
    if inbox == "approved" and assignments_enabled:
        visible.sort(key=lambda row: (row["approved_at"], row["public_ref"]), reverse=True)
    if sort == "oldest":
        visible.reverse()
    elif sort == "priority":
        visible.sort(key=lambda row: PRIORITY[row["category"]])
    return {
        "rows": visible,
        "inbox": inbox,
        "inboxes": [
            {"key": key, "label": label,
             "count": sum(_inbox_matches(row, key) for row in described)}
            for key, label in INBOXES.items()
            if assignments_enabled or key not in {"mine", "shared"}
        ],
        "sort": sort,
        "sorts": [{"key": key, "label": label} for key, label in SORTS.items()],
        "filters": [
            {"key": key, "label": label, "count": counts[key]} for key, label in FILTERS.items()
        ],
        "selected_filter": selected_filter,
        "query": query,
        "total": len(described),
        "matched_total": len(matched),
        "visible_total": len(visible),
    }
