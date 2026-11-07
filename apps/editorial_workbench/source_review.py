"""Inspect saved or example source events against one fixed development draft."""

from django.core.exceptions import TooManyFieldsSent
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.fast9_case_source_join import draft_source_review
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import JournalError, read_source_history

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
        events = read_source_history(directory, CASE_KEY, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return failure(request, "تعذّرت قراءة سجل المصدر أو التحقق من سلامة أحداثه.", 503)
    if not events:
        return failure(request, "لا توجد أحداث محفوظة لهذه القضية في السجل المحلي.", 404)
    return _render_review(request, events)


def _render_review(request, events, *, sample=None):
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
            "timeline": timeline,
            "original": timeline[0]["body"],
            "latest": timeline[-1]["body"],
        },
    )
    response["Cache-Control"] = "no-store"
    return response
