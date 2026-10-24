"""Loopback-only, GET/HEAD navigation over fixed synthetic investigation data."""

from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_workbench.services import WorkbenchDataError

from .services import STATUSES, build_investigation, summarize


def _exact(text: str) -> str:
    # Escape untrusted text first. Character references preserve CR/CRLF through
    # HTML parsing; the template's <code> child retains initial newlines in <pre>.
    return mark_safe(str(escape(text)).replace("\r", "&#13;"))


def _url(key: str | None = None, **filters: str) -> str:
    base = (
        reverse("reference_triage:detail", args=[key]) if key else reverse("reference_triage:index")
    )
    query = urlencode({name: value for name, value in filters.items() if value})
    return base + ("?" + query if query else "")


def _failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "reference_triage/error.html", {"message": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def investigation(request: HttpRequest, key: str | None = None) -> HttpResponse:
    local_only(request)
    try:
        query = request.GET
        status, batch_id = query.get("status", ""), query.get("batch", "")
        if (
            set(query) - {"status", "batch"}
            or any(len(query.getlist(name)) != 1 for name in query)
            or status not in {"", *(value for value, _ in STATUSES)}
            or len(batch_id) > 100
            or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in batch_id)
        ):
            raise ValueError("invalid_query")
    except (ValueError, TooManyFieldsSent):
        return _failure(request, "معايير غير صالحة. اختر الحالة والدفعة من القائمة.", 400)
    try:
        report = build_investigation()
    except WorkbenchDataError:
        return _failure(
            request,
            "تعذر تحميل العينات الاصطناعية بأمان. عد إلى القائمة وأعد المحاولة؛ لا تستكمل دليلًا مفقودًا بالتخمين.",
            503,
        )
    if batch_id and batch_id not in {batch.batch_id for batch in report.batches}:
        return _failure(request, "الدفعة غير معروفة. اختر دفعة اصطناعية من القائمة.", 400)
    selected = next((row for row in report.cases if row.case.key == key), None)
    if key is not None and selected is None:
        return _failure(request, "السجل الاصطناعي غير موجود. اختر سجلًا من القائمة.", 404)
    filtered = tuple(
        row
        for row in report.cases
        if (not batch_id or row.batch_id == batch_id)
        and (
            not status
            or (status == "missing" and not row.references)
            or any(ref.status == status for ref in row.references)
        )
    )
    filters = {"status": status, "batch": batch_id}
    rows = tuple(
        {
            "row": row,
            "url": _url(row.case.key, **filters),
            "question": _exact(row.case.question or "لم يرد نص سؤال"),
            "workbench_url": reverse("editorial_workbench:detail", args=[row.case.key]),
        }
        for row in filtered
    )
    position = next((i for i, row in enumerate(filtered) if row.case.key == key), None)
    previous_url = rows[position - 1]["url"] if position is not None and position > 0 else None
    next_url = (
        rows[position + 1]["url"] if position is not None and position + 1 < len(rows) else None
    )
    references = (
        tuple(
            {
                "ref": ref,
                "source": _exact(ref.source_text),
                "original": _exact(ref.original_identity),
                "verified": _exact(ref.verified_identity),
                "evidence": _exact(ref.evidence),
            }
            for ref in selected.references
        )
        if selected
        else ()
    )
    response = render(
        request,
        "reference_triage/investigation.html",
        {
            "rows": rows,
            "selected": selected,
            "references": references,
            "summary": report.summary,
            "filtered_summary": summarize(filtered),
            "batches": report.batches,
            "batch_id": batch_id,
            "status": status,
            "statuses": STATUSES,
            "batch_rows": tuple(
                {"batch": batch, "url": _url(batch=batch.batch_id, status=status)}
                for batch in report.batches
            ),
            "return_url": _url(**filters),
            "previous_url": previous_url,
            "next_url": next_url,
            "outside_filter": selected is not None and position is None,
            "workbench_url": reverse("editorial_workbench:detail", args=[key])
            if selected
            else None,
            "question": _exact(selected.case.question or "لم يرد نص سؤال") if selected else "",
            "source": _exact(selected.case.raw_source) if selected else "",
        },
    )
    response["Cache-Control"] = "no-store"
    return response
