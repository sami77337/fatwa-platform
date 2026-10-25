"""Loopback-only GET inspection over fixed, source-pinned synthetic contracts."""

import re
from pathlib import Path

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only

from .services import build_catalog, evaluate
from .sources import SourceUnavailable


def _failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "permission_lab/error.html", {"message": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _selection(request: HttpRequest) -> dict[str, str]:
    # Reject oversized raw queries before Django allocates parsed parameter lists.
    if len(request.META.get("QUERY_STRING", "")) > 1024:
        raise ValueError("query_too_long")
    query = request.GET
    if not query:
        return {}
    if set(query) != {"actor", "action", "resource"} or any(
        len(query.getlist(key)) != 1 for key in query
    ):
        raise ValueError("exact_triple_required")
    selected = {key: query[key] for key in ("actor", "action", "resource")}
    if any(re.fullmatch(r"[A-Za-z0-9_:.-]{1,96}", value) is None for value in selected.values()):
        raise ValueError("invalid_identifier")
    return selected


@require_safe
def inspect(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        selected = _selection(request)
    except (ValueError, TooManyFieldsSent):
        return _failure(
            request, "اختيار غير صالح. حدد الدور الافتراضي والفعل والمورد من القوائم.", 400
        )
    try:
        catalog = build_catalog()
        if selected and (
            selected["actor"] not in catalog.actors
            or selected["action"] not in catalog.actions
            or selected["resource"] not in {item.id for item in catalog.resources}
        ):
            return _failure(request, "اختيار غير معروف. استخدم المعرّفات المتاحة في المختبر.", 400)
        decision = evaluate(**selected) if selected else None
    except SourceUnavailable:
        return _failure(
            request, "تعذر التحقق من مصادر المختبر. يظل القرار منعًا؛ أعد المحاولة لاحقًا.", 503
        )
    response = render(
        request,
        "permission_lab/inspect.html",
        {"catalog": catalog, "selected": selected, "decision": decision},
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.META.get("QUERY_STRING", ""):
            return _failure(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        content = Path(__file__).with_name("lab.css").read_bytes()
    except OSError:
        return _failure(request, "تعذر تحميل التنسيق المحلي.", 503)
    response = HttpResponse(content, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
