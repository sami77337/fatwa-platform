"""Loopback synthetic previews and an opt-in Wave7 persisted read-only adapter."""

import ipaddress
import os
import re
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.exceptions import TooManyFieldsSent
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .asset_integrity import AssetIntegrityError, verified_preview_css
from .fixtures import ROWS, SCHEMA, STATUSES
from .integration import (
    ISSUE_LABELS, STATUS_LABELS, SYNTHETIC_BATCHES, build_batch_preview_rows, build_preview_rows,
)


def local_only(request: HttpRequest) -> None:
    host = urlsplit("//" + request.get_host()).hostname
    try:
        peer_local = ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback
    except ValueError:
        peer_local = False
    if (
        os.environ.get("FATWA_PRODUCTION", "0") != "0"
        or getattr(settings, "FATWA_PRODUCTION", False)
        or str(settings.SETTINGS_MODULE).endswith(".production")
        or host not in {"localhost", "127.0.0.1", "::1"}
        or not peer_local
    ):
        raise Http404


@require_safe
def preview(request: HttpRequest, ident: str | None = None) -> HttpResponse:
    local_only(request)
    query = request.GET
    error = ""
    if (
        set(query) - {"q", "status"}
        or any(len(query.getlist(k)) != 1 for k in query)
        or len(query.get("q", "")) > 80
        or len(query.get("status", "")) > 32
        or any(ord(c) < 32 or ord(c) == 127 for c in query.get("q", ""))
        or query.get("status", "") not in {"", *STATUSES}
    ):
        error = "invalid_filter"
    q = query.get("q", "").strip() if not error else ""
    status = query.get("status", "") if not error else ""
    row = None
    if ident is not None:
        row = next((item for item in ROWS if item.external_id == ident), None)
        if row is None:
            raise Http404
    rows = tuple(
        item
        for item in ROWS
        if (not status or item.status == status)
        and (not q or q.casefold() in (item.title + item.question + item.external_id).casefold())
    )
    response = render(
        request,
        "editorial_demo/preview.html",
        {
            "row": row,
            "rows": rows,
            "q": q,
            "status": status,
            "statuses": STATUSES,
            "error": error,
            "schema": SCHEMA,
            "filter_query": urlencode({"q": q, "status": status}),
        },
        status=400 if error else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        payload = verified_preview_css()
    except AssetIntegrityError as exc:
        raise Http404("Unavailable local stylesheet") from exc
    response = HttpResponse(payload, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


def _failure(message: str, status: int) -> HttpResponse:
    response = HttpResponse(message, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _positive_query(value: str, maximum: int) -> int:
    if len(value) > 5 or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("invalid_page")
    number = int(value)
    if number > maximum:
        raise ValueError("invalid_page")
    return number


def _worklist_query(request: HttpRequest):
    query = request.GET
    if set(query) - {"batch", "row", "q", "status", "issue", "page", "page_size"} or any(
        len(query.getlist(key)) != 1 for key in query
    ):
        raise ValueError("invalid_query")
    q, status, issue = query.get("q", ""), query.get("status", ""), query.get("issue", "")
    batch = query.get("batch", "default")
    if (
        len(q) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in q)
        or status not in {"", *STATUS_LABELS} or issue not in {"", *ISSUE_LABELS}
        or batch not in SYNTHETIC_BATCHES
    ):
        raise ValueError("invalid_query")
    selection = _positive_query(query["row"], 1000) if "row" in query else None
    return batch, selection, q, status, issue, _positive_query(
        query.get("page", "1"), 10000
    ), _positive_query(query.get("page_size", "20"), 50)


@require_safe
def pipeline_preview(request: HttpRequest, ident: str | None = None) -> HttpResponse:
    """Worklist over fixed fixtures; query parameters never supply records or source pins."""
    local_only(request)
    try:
        batch, selection, q, status, issue, page, page_size = _worklist_query(request)
        if ident is not None and selection is not None:
            raise ValueError("conflicting_row_selection")
    except (ValueError, TooManyFieldsSent):
        return _failure("معايير تصفية غير صالحة", 400)
    try:
        rows = build_preview_rows() if batch == "default" else build_batch_preview_rows(batch)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return _failure("المعاينة الاصطناعية غير متاحة", 503)
    matches = tuple(candidate for candidate in rows if candidate.external_id == ident)
    row = matches[0] if len(matches) == 1 else None
    if selection is not None:
        if selection > len(rows):
            return _failure("السجل غير موجود", 404)
        row = rows[selection - 1]
    if ident is not None and row is None:
        return _failure("السجل غير موجود", 404)
    term = q.strip().casefold()
    filtered_entries = tuple((number, candidate) for number, candidate in enumerate(rows, 1) if
                     (not status or candidate.status == status)
                     and (not issue or issue in candidate.issue_codes)
                     and (not term or term in (candidate.external_id + candidate.question).casefold()))
    filtered = tuple(candidate for _, candidate in filtered_entries)
    matched_count = len(filtered)
    page_count = max(1, (matched_count + page_size - 1) // page_size)
    if page > page_count:
        return _failure("الصفحة المطلوبة غير موجودة", 404)
    start = (page - 1) * page_size
    references = tuple(ref for candidate in rows for ref in candidate.references)
    summary = {
        "total": len(rows),
        "ready": sum(candidate.status == "ready-for-editor" for candidate in rows),
        "needs_review": sum(candidate.status == "needs-editor-review" for candidate in rows),
        "blocked": sum(candidate.status == "blocked-invalid" for candidate in rows),
        "drafts": sum(candidate.draft_created for candidate in rows),
        "verified_references": sum(ref.status == "verified" for ref in references),
        "unverified_references": sum(ref.status != "verified" for ref in references),
    }
    params = {"q": q, "status": status, "issue": issue, "page_size": page_size, "page": page}
    if batch != "default" or "batch" in request.GET:
        params["batch"] = batch
    # Build list links from the named route, never from a detail URL or user input.
    from django.urls import reverse

    list_url = reverse("editorial_pipeline")
    previous_url = list_url + "?" + urlencode({**params, "page": page - 1}) if page > 1 else None
    next_url = list_url + "?" + urlencode({**params, "page": page + 1}) if page < page_count else None
    # Stable batch-local input ordinals address every retained row, including
    # duplicate, missing and slash-containing opaque IDs, without new routes.
    display_rows = tuple({
        "item": candidate,
        "detail_url": list_url + "?" + urlencode({**params, "batch": batch, "row": number}),
    } for number, candidate in filtered_entries[start:start + page_size])
    response = render(request, "editorial_demo/pipeline.html", {
        "row": row, "rows": filtered[start:start + page_size],
        "display_rows": display_rows,
        "batch": batch, "batches": SYNTHETIC_BATCHES, "batch_label": SYNTHETIC_BATCHES[batch],
        "q": q, "status": status, "issue": issue,
        "statuses": STATUS_LABELS, "issues": ISSUE_LABELS,
        "summary": summary, "matched_count": matched_count,
        "page": page, "page_count": page_count, "page_size": page_size,
        "previous_url": previous_url, "next_url": next_url,
        "filter_query": urlencode(params),
    })
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def persisted_review(request: HttpRequest) -> HttpResponse:
    """Wave7-only persisted synthetic GET/HEAD adapter; shared routes opt in separately."""
    local_only(request)
    from django.apps import apps
    if (getattr(settings, 'WAVE7_READS_ENABLED', False) is not True
            or not apps.is_installed('apps.intake_workflow')):
        return _failure('المعاينة المحفوظة غير متاحة', 404)
    from apps.reference import services
    if not services._workflow_reads_enabled():
        return _failure('المعاينة المحفوظة غير متاحة', 404)
    from django.db import DatabaseError
    from django.urls import reverse
    from apps.intake_workflow import contracts as c, guards, review
    try:
        query = request.GET
        if set(query) - {'batch','row','q','mode','intake_status','review_status','page','page_size'} or any(
                len(query.getlist(key)) != 1 for key in query):
            raise c.ContractError('review: invalid_query')
        stored = review.load_review_worklist(batch_id=query.get('batch'),row_id=query.get('row'),
            q=query.get('q',''),mode=query.get('mode','normalized'),intake_status=query.get('intake_status',''),review_status=query.get('review_status',''),
            page=_positive_query(query.get('page','1'),10000),
            page_size=_positive_query(query.get('page_size','20'),50),synthetic_fixtures_only=True)
    except (ValueError, TooManyFieldsSent) as exc:
        return _failure('معايير أو سجل غير صالح', getattr(exc,'status_code',400))
    except (guards.SyntheticWriteDenied, DatabaseError):
        return _failure('المعاينة المحفوظة غير متاحة',503)
    base = reverse('wave7_editorial_review')
    params = {'q':stored.q,'mode':stored.mode,'intake_status':stored.intake_status,'review_status':stored.review_status,
              'page':stored.page,'page_size':stored.page_size}
    if stored.batch_id:
        params['batch'] = str(stored.batch_id)
    response = render(request,'editorial_demo/pipeline.html',{
        'stored':stored,'stored_return_url':base+'?'+urlencode(params),
        'stored_list_url':base,
        'stored_display_rows':tuple({'item':row,'detail_url':base+'?'+urlencode({**params,'row':str(row.id)})}
                                   for row in stored.rows),
        'stored_previous_url':base+'?'+urlencode({**params,'page':stored.page-1}) if stored.page>1 else None,
        'stored_next_url':base+'?'+urlencode({**params,'page':stored.page+1}) if stored.page<stored.page_count else None,
        'stored_intake_statuses':{'RECEIVED':'مستلم','READY_FOR_EDITOR':'جاهز للمحرر','NEEDS_REVIEW':'يحتاج مراجعة','BLOCKED_INVALID':'مدخل محجوب'},
        'stored_review_statuses':{'UNREVIEWED':'لم تبدأ المراجعة','IN_REVIEW':'قيد المراجعة','NEEDS_CHANGES':'يحتاج تعديلًا','REVIEWED_INTERNAL':'مراجعة داخلية فقط'},
    })
    response['Cache-Control']='no-store'
    return response
