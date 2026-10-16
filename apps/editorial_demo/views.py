"""Read-only local development screens. No database, uploads or workflow calls."""

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .fixtures import ROWS, SCHEMA, STATUSES
from .integration import STATUS_LABELS, build_preview_rows


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
    return HttpResponse(
        Path(__file__).with_name("preview.css").read_text(encoding="utf-8"),
        content_type="text/css; charset=utf-8",
    )


@require_safe
def pipeline_preview(request: HttpRequest, ident: str | None = None) -> HttpResponse:
    """Separate read-only D1+D3+D2 demonstration; never use request-supplied records."""
    local_only(request)
    query = request.GET
    if (
        set(query) - {"q", "status"}
        or any(len(query.getlist(key)) != 1 for key in query)
        or len(query.get("q", "")) > 80
        or len(query.get("status", "")) > 32
        or any(ord(char) < 32 or ord(char) == 127 for char in query.get("q", ""))
        or query.get("status", "") not in {"", *STATUS_LABELS}
    ):
        response = HttpResponse("معايير تصفية غير صالحة", status=400)
        response["Cache-Control"] = "no-store"
        return response
    q = query.get("q", "").strip()
    status = query.get("status", "")
    try:
        rows = build_preview_rows()
    except (ValueError, TypeError, KeyError, IndexError):
        # Never leak source identity, fixture bytes, tracebacks or internal diagnostics.
        response = HttpResponse("المعاينة الاصطناعية غير متاحة", status=503)
        response["Cache-Control"] = "no-store"
        return response
    row = next((candidate for candidate in rows if candidate.external_id == ident), None)
    if ident is not None and row is None:
        raise Http404
    filtered = tuple(
        candidate
        for candidate in rows
        if (not status or candidate.status == status)
        and (not q or q.casefold() in (candidate.external_id + candidate.question).casefold())
    )
    response = render(
        request,
        "editorial_demo/pipeline.html",
        {
            "row": row,
            "rows": filtered,
            "q": q,
            "status": status,
            "statuses": STATUS_LABELS,
            "filter_query": urlencode({"q": q, "status": status}),
        },
    )
    response["Cache-Control"] = "no-store"
    return response
