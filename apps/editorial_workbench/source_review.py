"""Local inspection of fixed source-change examples against one actual fixture draft."""

from dataclasses import replace

from django.core.exceptions import TooManyFieldsSent
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.fast9_case_source_join import draft_source_review
from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt

from .views import _packet_exact, failure

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


def _sample_events(sample):
    first = source_receipt(CASE_KEY)
    if sample == "received":
        return (first,)
    edit = replace(
        first,
        event_id="edit-example",
        prior_event_id=first.event_id,
        kind="corrected",
        body_utf8=CORRECTION_BODIES[0],
    )
    if sample == "corrected":
        return first, edit
    if sample == "deleted":
        last = replace(
            edit,
            event_id="delete-example",
            prior_event_id=edit.event_id,
            kind="deleted",
            body_utf8=None,
        )
    else:
        last = replace(
            edit,
            event_id="restore-example",
            prior_event_id=edit.event_id,
            body_utf8=first.body_utf8,
        )
    return first, edit, last


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
        events = _sample_events(sample)
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
            "selected": sample,
            "timeline": timeline,
            "original": timeline[0]["body"],
            "latest": timeline[-1]["body"],
        },
    )
    response["Cache-Control"] = "no-store"
    return response
