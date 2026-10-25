"""GET/HEAD-only desk; existing loopback guard runs before loading any fixtures."""

from pathlib import Path
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
from apps.revision_core.revision_history import HistoryDataError

from .services import REASONS, STATUSES, FollowupRow, build_followup, select_followup


def _exact(text: str) -> str:
    # Escape markup before preserving CR through HTML parsing. Templates put
    # code inside pre so initial newlines are not stripped by the browser.
    return mark_safe(str(escape(text)).replace("\r", "&#13;"))


def _url(filters: dict[str, str], key: str | None = None) -> str:
    base = (
        reverse("editorial_followup:detail", args=[key])
        if key
        else reverse("editorial_followup:index")
    )
    return base + ("?" + urlencode(filters) if filters else "")


def _failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "editorial_followup/error.html", {"message": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _filters(request: HttpRequest) -> dict[str, str]:
    query = request.GET
    reason, batch, status = (query.get(name, "") for name in ("reason", "batch", "status"))
    if (
        set(query) - {"reason", "batch", "status"}
        or any(len(query.getlist(name)) != 1 for name in query)
        or reason not in {"", *(code for code, _ in REASONS)}
        or status not in {"", *(code for code, _ in STATUSES)}
        or len(batch) > 100
        or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in batch)
    ):
        raise ValueError("invalid_filters")
    return {
        name: value
        for name, value in (("reason", reason), ("batch", batch), ("status", status))
        if value
    }


@require_safe
def desk(request: HttpRequest, key: str | None = None) -> HttpResponse:
    local_only(request)
    try:
        filters = _filters(request)
    except (ValueError, TooManyFieldsSent):
        return _failure(
            request, "معايير غير صالحة. اختر سبب المتابعة والدفعة وحالة الاستلام من القوائم.", 400
        )
    try:
        catalog = build_followup()
    except (WorkbenchDataError, HistoryDataError):
        return _failure(
            request,
            "تعذر تحميل وقائع المتابعة بأمان. أعد المحاولة؛ لم يُستنتج خلو السجلات من الملاحظات.",
            503,
        )
    if filters.get("batch") and filters["batch"] not in {
        batch.batch_id for batch in catalog.batches
    }:
        return _failure(request, "الدفعة غير معروفة. اختر دفعة اصطناعية من القائمة.", 400)
    selection = select_followup(catalog.rows, key=key, **filters)
    selected = selection.selected
    if key is not None and selected is None:
        return _failure(request, "السجل غير موجود. عد إلى قائمة المتابعة لاختيار هوية متاحة.", 404)

    def detail_url(item: FollowupRow | None) -> str | None:
        return _url(filters, item.row.case.key) if item else None

    case = selected.row.case if selected else None
    workbench_url = reverse("editorial_workbench:detail", args=[key]) if case else None
    investigation_url = reverse("reference_triage:detail", args=[key]) if case else None
    response = render(
        request,
        "editorial_followup/desk.html",
        {
            "filters": filters,
            "reasons": REASONS,
            "statuses": STATUSES,
            "batches": catalog.batches,
            "total": len(catalog.rows),
            "followup_total": sum(bool(item.reasons) for item in catalog.rows),
            "selection": selection,
            "selected": selected,
            "rows": tuple(
                {
                    "item": item,
                    "url": detail_url(item),
                    "question": _exact(
                        item.row.case.question
                        if item.row.case.question is not None
                        else "لم يرد نص سؤال"
                    ),
                }
                for item in selection.rows
            ),
            "question": _exact(case.question if case.question is not None else "لم يرد نص سؤال")
            if case
            else "",
            "source": _exact(case.raw_source) if case else "",
            "previous_url": detail_url(selection.previous),
            "next_url": detail_url(selection.next),
            "return_url": _url(filters),
            "workbench_url": workbench_url,
            "investigation_url": investigation_url,
            "receipt_url": workbench_url
            + "?"
            + urlencode({"revision": case.record.current.number})
            + "#snapshot"
            if case and case.record
            else None,
            "reference_rows": tuple(
                {"ref": ref, "url": investigation_url + f"#reference-{ref['reference_ordinal']}"}
                for ref in selected.references
            )
            if selected
            else (),
            # Batch parse failures are not rejected rows; no fictitious row/receipt.
            # Reason and row-status filters do not describe a batch without rows.
            "batch_errors": tuple(
                batch
                for batch in catalog.batches
                if batch.source
                and batch.source.error_code
                and (not filters.get("batch") or batch.batch_id == filters["batch"])
            ),
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.GET:
            return _failure(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        content = Path(__file__).with_name("followup.css").read_bytes()
    except TooManyFieldsSent:
        return _failure(request, "معايير غير صالحة.", 400)
    except OSError:
        return _failure(request, "تعذر تحميل تنسيق المكتب.", 503)
    response = HttpResponse(content, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
