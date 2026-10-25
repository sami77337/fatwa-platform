"""Loopback-only research navigation from fixed synthetic reference cases."""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_workbench.services import WorkbenchDataError
from apps.reference_triage.services import build_investigation

from .services import bridge_reference


def _exact(text: str) -> str:
    # HTML normalizes literal CRs. Escaping first and then encoding CR preserves
    # the original text without admitting markup; <pre><code> keeps leading LF.
    return mark_safe(str(escape(text)).replace("\r", "&#13;"))


def _failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    return render(request, "research_bridge/error.html", {"message": message}, status=status)


@never_cache
@require_safe
def research(request: HttpRequest, key: str | None = None) -> HttpResponse:
    try:
        local_only(request)
    except Http404:
        return HttpResponse(status=404)
    # No query parameters can override fixture identity, pins or catalog source.
    # Check the raw string before QueryDict parsing, including excessive fields.
    if request.META.get("QUERY_STRING"):
        return _failure(request, "لا تقبل هذه الشاشة معايير إضافية. اختر سجلًا من القائمة.", 400)
    try:
        report = build_investigation()
    except WorkbenchDataError:
        return _failure(
            request,
            "تعذر تحميل العينات الاصطناعية بأمان. عد إلى القائمة وأعد المحاولة؛ لا تستكمل دليلًا بالتخمين.",
            503,
        )
    selected = next((row for row in report.cases if row.case.key == key), None)
    if key is not None and selected is None:
        return _failure(request, "السجل الاصطناعي غير موجود. اختر سجلًا من القائمة.", 404)
    rows = tuple(
        {
            "row": row,
            "url": reverse("research_bridge:detail", args=[row.case.key]),
            "question": _exact(row.case.question or "لم يرد نص سؤال"),
            "triage_url": reverse("reference_triage:detail", args=[row.case.key]),
            "workbench_url": reverse("editorial_workbench:detail", args=[row.case.key]),
        }
        for row in report.cases
    )
    position = next((i for i, row in enumerate(report.cases) if row.case.key == key), None)
    references = (
        tuple(
            {
                "ref": ref,
                "source": _exact(ref.source_text),
                "original": _exact(ref.original_identity),
                "result": bridge_reference(ref),
            }
            for ref in selected.references
        )
        if selected
        else ()
    )
    return render(
        request,
        "research_bridge/research.html",
        {
            "rows": rows,
            "selected": selected,
            "references": references,
            "question": _exact(selected.case.question or "لم يرد نص سؤال") if selected else "",
            "previous_url": rows[position - 1]["url"]
            if position is not None and position > 0
            else None,
            "next_url": rows[position + 1]["url"]
            if position is not None and position + 1 < len(rows)
            else None,
            "triage_url": reverse("reference_triage:detail", args=[key]) if selected else None,
            "workbench_url": reverse("editorial_workbench:detail", args=[key])
            if selected
            else None,
        },
    )
