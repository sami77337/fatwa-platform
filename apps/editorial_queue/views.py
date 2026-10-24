"""GET/HEAD-only SSR queue; all fixtures loaded after the existing local guard."""

from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_workbench.services import WorkbenchDataError
from apps.fatwa_drafts.revision_audit import build_revision_audit
from apps.revision_core.revision_history import HistoryDataError

from .services import REFERENCE_FILTERS, STATUSES, QueueRow, build_queue_catalog, select_queue


def _url(name: str, filters: dict[str, str], key: str | None = None) -> str:
    base = reverse(name, args=[key] if key is not None else None)
    return base + ("?" + urlencode(filters) if filters else "")


def _error(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "editorial_queue/error.html", {"message": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _filters(request: HttpRequest) -> dict[str, str]:
    query = request.GET
    q, status, refs = query.get("q", ""), query.get("status", ""), query.get("refs", "")
    batch = query.get("batch", "")
    if (
        set(query) - {"q", "status", "refs", "batch"}
        or any(len(query.getlist(key)) != 1 for key in query)
        or len(q) > 80
        or any(ord(char) < 32 or ord(char) == 127 for char in q)
        or status not in {"", *(code for code, _ in STATUSES)}
        or refs not in {"", *(code for code, _ in REFERENCE_FILTERS)}
        or len(batch) > 100
        or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in batch)
    ):
        raise ValueError("invalid_filter")
    q.encode("utf-8", errors="strict")
    return {
        key: value
        for key, value in (("q", q), ("status", status), ("refs", refs), ("batch", batch))
        if value
    }


@require_safe
def queue(request: HttpRequest, key: str | None = None) -> HttpResponse:
    local_only(request)
    try:
        filters = _filters(request)
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return _error(
            request, "التصفية غير صالحة. اختر من الحالات المتاحة واستخدم بحثًا حتى ٨٠ حرفًا.", 400
        )
    try:
        catalog = build_queue_catalog()
        rows = catalog.rows
        if filters.get("batch") and filters["batch"] not in {
            batch.batch_id for batch in catalog.batches
        }:
            return _error(request, "الدفعة غير معروفة. اختر دفعة اصطناعية من القائمة.", 400)
        selection = select_queue(rows, key=key, **filters)
        if key is not None and selection.selected is None:
            return _error(
                request, "السجل الاصطناعي غير موجود. عد إلى القائمة لاختيار سجل متاح.", 404
            )
        selected = selection.selected
        audit = (
            build_revision_audit(selected.case.record, synthetic_fixtures_only=True)
            if selected is not None and selected.case.record is not None
            else None
        )
    except (WorkbenchDataError, HistoryDataError):
        return _error(
            request, "تعذر تحميل قائمة العينات بأمان. أعد المحاولة أو ارجع إلى القائمة.", 503
        )

    def detail_url(row: QueueRow | None) -> str | None:
        return _url("editorial_queue:detail", filters, row.case.key) if row else None

    workbench_url = (
        reverse("editorial_workbench:detail", args=[key]) if selected is not None else ""
    )
    response = render(
        request,
        "editorial_queue/queue.html",
        {
            "selection": selection,
            "selected": selected,
            "rows": tuple({"item": row, "url": detail_url(row)} for row in selection.rows),
            "total": len(rows),
            "batches": catalog.batches,
            "batch_rows": tuple(
                {
                    "summary": batch,
                    "url": _url("editorial_queue:index", {"batch": batch.batch_id}),
                }
                for batch in catalog.batches
            ),
            "selected_batch": next(
                (batch for batch in catalog.batches if batch.batch_id == filters.get("batch")),
                None,
            ),
            "record_batch": next(
                (
                    batch
                    for batch in catalog.batches
                    if selected and batch.batch_id == selected.batch_id
                ),
                None,
            ),
            "filters": filters,
            "statuses": STATUSES,
            "reference_filters": REFERENCE_FILTERS,
            "return_url": _url("editorial_queue:index", filters),
            "previous_url": detail_url(selection.previous),
            "next_url": detail_url(selection.next),
            "workbench_url": workbench_url,
            "history_rows": tuple(
                {
                    "entry": entry,
                    "url": workbench_url
                    + "?"
                    + urlencode({"revision": entry.revision.number})
                    + "#snapshot",
                    "history_url": workbench_url + f"#revision-{entry.revision.number}",
                }
                for entry in selected.history
            )
            if selected
            else (),
            "audit": audit,
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.GET:
            return _error(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        payload = Path(__file__).with_name("queue.css").read_bytes()
    except TooManyFieldsSent:
        return _error(request, "معايير غير صالحة.", 400)
    except OSError:
        return _error(request, "تعذر تحميل تنسيق القائمة. أعد المحاولة.", 503)
    response = HttpResponse(payload, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
