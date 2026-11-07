"""Inspect saved or example source events against one fixed development draft."""

from datetime import datetime

from django.core.exceptions import TooManyFieldsSent
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.fast9_case_source_join import draft_source_review
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import JournalError, read_case_review

from .views import _packet_exact, _source_journal_directory, failure

# Only this original intake row has both a bound source envelope and a receipt-stage draft.
CASE_KEY = "intake-7"
DRAFT_REVISION = 1
SAMPLES = {
    "received": "الاستلام فقط",
    "corrected": "بعد التصحيح",
    "deleted": "بعد الحذف",
    "restored": "بعد إعادة النص الأصلي",
}
STATUS = {
    "SOURCE_TEXT_UNCHANGED": "يطابق نص الاستلام النص في آخر حدث معروض.",
    "SOURCE_TEXT_CHANGED_REVIEW_NEEDED": "تغيّر نص المصدر بعد الاستلام. راجع السؤال قبل مواصلة العمل على المسودة.",
    "SOURCE_DELETED_REVIEW_NEEDED": "سُجّل حذف المصدر بعد الاستلام. راجع السؤال المحفوظ وتاريخ التصحيح.",
}
KINDS = {"received": "الاستلام", "corrected": "تصحيح", "deleted": "حذف"}


@require_safe
def source_review(request):
    local_only(request)
    try:
        query = request.GET
        sample = query.get("sample", "received")
        if set(query) - {"sample"} or len(query.getlist("sample")) > 1 or sample not in SAMPLES:
            return failure(request, "اختر أحد أمثلة تغيّر المصدر المعروضة.", 400)
    except TooManyFieldsSent:
        return failure(request, "تعذّرت قراءة خيار العرض.", 400)
    try:
        events = sample_source_events(CASE_KEY, sample)
    except ValueError:
        return failure(request, "تعذّرت قراءة أحداث المثال.", 503)
    return _render_review(request, events, sample=sample)


@require_safe
def source_journal_review(request):
    local_only(request)
    if request.META.get("QUERY_STRING"):
        return failure(request, "تُعرض الأحداث المحفوظة لهذه القضية دون معايير إضافية.", 400)
    directory = _source_journal_directory()
    if directory is None:
        return failure(request, "لم يُضبط مسار مطلق لسجل المصدر المحلي.", 503)
    try:
        snapshot = read_case_review(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return failure(request, "تعذّرت قراءة سجل المصدر أو التحقق من سلامة أحداثه.", 503)
    if not snapshot.events:
        return failure(request, "لا توجد أحداث محفوظة لهذه القضية في السجل المحلي.", 404)
    return _render_review(request, snapshot.events, snapshot=snapshot)


def clarification_rows(snapshot):
    seen = snapshot.receipt.reply_digest if snapshot.receipt else ""
    seen_number = next((e.number for e in snapshot.clarifications if e.digest == seen), 0)
    return [
        {
            "kind": e.kind,
            "exact": _packet_exact(e.text),
            "number": e.number,
            "source_count": e.source_count,
            "recorded_at": datetime.fromisoformat(e.recorded_at),
            "unread": e.kind == "reply" and e.number > seen_number,
        }
        for e in snapshot.clarifications
    ]


def reading_state(receipt, count, draft_digest, reply_digest=""):
    # The journal validates every receipt against its case and source prefix.
    if receipt is None:
        return "unseen"
    if receipt.draft_digest != draft_digest:
        return "draft_changed"
    if receipt.count != count:
        return "changed"
    return "current" if receipt.reply_digest == reply_digest else "reply_changed"


def _render_review(request, events, *, sample=None, snapshot=None):
    receipt = snapshot.receipt if snapshot else None
    try:
        observation = draft_source_review.inspect_draft_source(
            CASE_KEY, DRAFT_REVISION, events, synthetic_fixtures_only=True
        )
    except ValueError:
        return failure(request, "تعذّرت مطابقة المسودة بالمصدر والتحقق من ترتيب الأحداث.", 503)

    timeline = [
        {
            "kind": e.kind,
            "label": KINDS[e.kind],
            "body": _packet_exact(e.body_utf8.decode("utf-8")) if e.body_utf8 is not None else None,
        }
        for e in events
    ]
    response = render(
        request,
        "editorial_workbench/source_review.html",
        {
            "observation": observation,
            "status_message": STATUS[observation.status],
            "samples": SAMPLES,
            "source_journal_enabled": _source_journal_directory() is not None,
            "selected": sample,
            "reading_state": reading_state(
                receipt,
                len(events),
                observation.draft_revision_sha256,
                snapshot.reply_digest if snapshot else "",
            ),
            "thread": clarification_rows(snapshot) if snapshot else [],
            "read_through": receipt.count if receipt else None,
            "timeline": timeline,
            "original": timeline[0]["body"],
            "latest": timeline[-1]["body"],
        },
    )
    response["Cache-Control"] = "no-store"
    return response
