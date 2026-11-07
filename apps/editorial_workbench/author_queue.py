"""The saved intake cases, their next actions and the author's drafts."""

from django.core.exceptions import SuspiciousOperation
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.fast9_case_source_join.source_journal import JournalError, history_digest, read_desk_cases
from apps.reference.normalization import normalize_title

from .author_access import draft_history_required
from .reviewer_access import signed_in
from .services import build_cases
from .source_review import CASE_KEY, KINDS
from .views import _packet_exact, _source_journal_directory

FILTERS = {
    "all": "كل القضايا",
    "action": "تحتاج إلى إجراء",
    "waiting": "بانتظار ردّ",
    "unread": "ردود جديدة",
    "drafts": "لها مسودة",
    "updated": "تغيّرت وقائعها بعد الكتابة",
    "intake": "تحتاج إلى فحص الاستلام",
    "notes": "ملاحظات تعديل مفتوحة",
}


@draft_history_required
@require_safe
def author_queue(request, key=None):
    template = "editorial_workbench/author_queue.html"

    def error(message, status):
        return render(request, template, {"message": message}, status=status)

    try:
        params = request.GET
        if (
            (key and params)
            or set(params) - {"q", "state"}
            or any(len(params.getlist(k)) != 1 for k in params)
        ):
            return error("تعذّرت قراءة معايير العرض.", 400)
        q = params.get("q", "")
        selected = params.get("state", "all")
        if selected not in FILTERS or len(q) > 100:
            return error("اختر حالة معروضة واكتب عبارة بحث حتى 100 حرف.", 400)
    except SuspiciousOperation:
        return error("تعذّرت قراءة معايير العرض.", 400)

    directory = _source_journal_directory()
    if directory is None:
        return error("لم يُضبط سجل التدريب المحلي.", 503)
    try:
        cases = read_desk_cases(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return error("تعذّرت قراءة قائمة القضايا المحفوظة.", 503)
    profiles = {p.key: p for p in build_cases()}
    is_author = signed_in(request, "author")
    context = {"is_author": is_author, "q": q, "selected": selected}
    if key:
        if key not in cases:
            raise Http404
        snapshot = cases[key]
        context.update(
            case=profiles[key],
            timeline=[
                {
                    "label": KINDS[e.kind],
                    "text": _packet_exact(e.body_utf8.decode())
                    if e.body_utf8 is not None
                    else None,
                }
                for e in snapshot.events
            ],
            can_compose=key == CASE_KEY,
        )
        return render(request, template, context)

    counts = dict.fromkeys(FILTERS, 0)
    rows = []
    needle = normalize_title(q)
    for case_key, snapshot in cases.items():
        profile = profiles[case_key]
        events = snapshot.events
        original = events[0].body_utf8.decode()
        latest = events[-1].body_utf8
        draft = snapshot.drafts[-1] if snapshot.drafts else None
        reviewable = case_key == CASE_KEY
        waiting = bool(snapshot.clarifications and snapshot.clarifications[-1].kind == "request")
        unread = bool(
            snapshot.reply_digest
            and (not snapshot.receipt or snapshot.reply_digest != snapshot.receipt.reply_digest)
        )
        updated = bool(
            draft
            and (
                draft.source_digest != history_digest(events)
                or draft.reply_digest != snapshot.reply_digest
            )
        )
        facets = {"all"}
        badges = []
        if not reviewable:
            facets.update(("action", "intake"))
            badges.append(FILTERS["intake"])
        if waiting:
            facets.add("waiting")
            badges.append(FILTERS["waiting"])
        if unread:
            facets.update(("action", "unread"))
            badges.append("ردّ جديد يحتاج إلى قراءة")
        if updated:
            facets.update(("action", "updated"))
            badges.append("تغيّرت الوقائع بعد آخر حفظ")
        open_note = (
            snapshot.draft_notes[-1]
            if snapshot.draft_notes and snapshot.draft_notes[-1].action == "request"
            else None
        )
        if open_note:
            facets.update(("notes", "action"))
            badges.append(
                "المؤلف لديه طلب تعديل"
                if draft.revision == open_note.revision
                else "نسخة جديدة بانتظار مراجعة الملاحظة"
            )
        if draft:
            facets.add("drafts")
            badges.append(f"مسودة محفوظة · النسخة {draft.revision}")
        elif reviewable and not waiting:
            facets.add("action")
            badges.append("متاحة لبدء مسودة")
        search_fields = [
            case_key,
            profile.external_id or "",
            original,
            latest.decode() if latest else "",
        ]
        if draft:
            search_fields.extend((draft.title, draft.body))
        search_fields.extend(turn.text for turn in snapshot.clarifications)
        if needle and not any(needle in normalize_title(value) for value in search_fields):
            continue
        for facet in facets:
            counts[facet] += 1
        if selected in facets:
            rows.append(
                {
                    "key": case_key,
                    "external_id": profile.external_id,
                    "title": draft.title if draft else "",
                    "question": latest.decode() if latest is not None else original,
                    "deleted": latest is None,
                    "source_url": reverse("desk_source", args=(case_key,)),
                    "reviewable": reviewable,
                    "badges": badges,
                    "draft": bool(draft),
                    "open_note": bool(open_note),
                    "rank": (not (unread or updated or open_note), not reviewable, case_key),
                }
            )
    context.update(
        rows=sorted(rows, key=lambda row: row["rank"]),
        tabs=[
            {"key": name, "label": label, "count": counts[name]} for name, label in FILTERS.items()
        ],
    )
    return render(request, template, context)
