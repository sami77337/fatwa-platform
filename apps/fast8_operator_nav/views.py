"""Read-only composition of the existing fixed synthetic service catalog."""

import re
from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.http import Http404, HttpRequest, HttpResponse
from django.template import engines
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_search.services import search_catalog, validate_query
from apps.editorial_workbench.services import WorkbenchDataError
from apps.revision_core.revision_history import (
    HistoryDataError,
    InvalidRevisionId,
    UnknownRevisionId,
    select_revisions,
)

from .links import service_links, service_url


def _response(request, context, status=200):
    source = Path(__file__).with_name("templates").joinpath("navigation.html").read_text("utf-8")
    context["index_url"] = reverse("fast8_operator_nav:index")
    response = HttpResponse(
        engines["django"].from_string(source).render(context, request), status=status
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _failure(request, message, status):
    return _response(request, {"error": message}, status)


def _parameters(request, key):
    query = request.GET
    if set(query) - ({"q", "page", "revision"} if key else {"q", "page"}) or any(
        len(query.getlist(name)) != 1 for name in query
    ):
        raise ValueError("invalid_parameters")
    page = query.get("page", "1")
    if re.fullmatch(r"[1-9][0-9]?", page) is None:
        raise ValueError("invalid_page")
    q = query.get("q", "")
    validate_query(q, "", "", int(page))
    if "revision" in query and re.fullmatch(r"[1-9][0-9]{0,5}", query["revision"]) is None:
        raise ValueError("invalid_revision")
    return q, int(page), query.get("revision")


def _url(key=None, params=None):
    url = (
        reverse("fast8_operator_nav:detail", args=[key])
        if key
        else reverse("fast8_operator_nav:index")
    )
    return url + ("?" + urlencode(params) if params else "")


def _exact(text):
    # Preserve CRLF, initial LF and Arabic Unicode through HTML parsing.
    return mark_safe("<code>" + str(escape(text)).replace("\r", "&#13;") + "</code>")


@require_safe
def navigation(request: HttpRequest, key: str | None = None) -> HttpResponse:
    try:
        local_only(request)
    except Http404:
        return HttpResponse(status=404, headers={"Cache-Control": "no-store"})
    try:
        q, page, revision_id = _parameters(request, key)
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return _failure(
            request, "معايير غير صالحة. استخدم بحثًا حتى ٨٠ حرفًا وهوية مراجعة صحيحة.", 400
        )
    try:
        catalog = build_queue_catalog()
        result = search_catalog(catalog, q=q, page=page)
    except (WorkbenchDataError, HistoryDataError):
        return _failure(request, "NOT_SUPPLIED — تعذر تحميل العينات الاصطناعية بأمان.", 503)
    except ValueError:
        return _failure(request, "صفحة البحث غير متاحة. عد إلى بداية البحث.", 400)
    selected = next((row for row in catalog.rows if row.case.key == key), None)
    if key is not None and selected is None:
        return _failure(request, "السجل غير موجود؛ لم يتم اختيار سجل بديل.", 404)
    revision = None
    if selected:
        if selected.history:
            try:
                revision_id = revision_id or str(selected.history[-1].revision.number)
                revision, _ = select_revisions(selected.history, revision_id, revision_id)
            except InvalidRevisionId:
                return _failure(request, "هوية المراجعة غير صالحة.", 400)
            except UnknownRevisionId:
                return _failure(request, "المراجعة غير موجودة في هذا السجل.", 404)
        elif revision_id is not None:
            return _failure(request, "لا توجد مراجعات لهذا السجل.", 400)
    filters = {"q": q, "page": page} if q else {}
    hits = tuple(
        {
            "hit": hit,
            "url": _url(
                hit.case_key, {**filters, **({"revision": hit.revision} if hit.revision else {})}
            )
            if hit.case_key
            else service_url("editorial_queue:index", params={"batch": hit.batch_id}),
        }
        for hit in result.hits
    )
    return _response(
        request,
        {
            "q": q,
            "result": result,
            "hits": hits,
            "selected": selected,
            "revision": revision,
            "rows": tuple({"row": row, "url": _url(row.case.key)} for row in catalog.rows),
            "links": service_links(key=key, revision=revision, q=q),
            "return_url": _url(params=filters),
            "previous_page": _url(params={**filters, "page": page - 1}) if page > 1 else None,
            "next_page": _url(params={**filters, "page": page + 1})
            if page < result.pages
            else None,
            "revisions": tuple(
                {
                    "number": entry.revision.number,
                    "url": _url(key, {**filters, "revision": entry.revision.number}),
                }
                for entry in selected.history
            )
            if selected
            else (),
            "question": _exact(selected.case.question or "لم يرد نص سؤال") if selected else "",
        },
    )


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    try:
        local_only(request)
    except Http404:
        return HttpResponse(status=404, headers={"Cache-Control": "no-store"})
    if request.META.get("QUERY_STRING"):
        return _failure(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
    response = HttpResponse(
        Path(__file__).with_name("navigation.css").read_bytes(),
        content_type="text/css; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
