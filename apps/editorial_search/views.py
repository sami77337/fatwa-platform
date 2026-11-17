"""Local GET/HEAD-only search. No input file, persistence or remote search adapter."""

import re
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
from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_workbench.services import WorkbenchDataError
from apps.research_bridge.services import bridge_reference
from apps.revision_core.revision_history import HistoryDataError

from .reference_cards import ReferenceNotFound, reference_card
from .services import SOURCE_TYPES, SearchHit, search_catalog, validate_query


def _error(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "editorial_search/error.html", {"message": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _parameters(request: HttpRequest) -> dict:
    query = request.GET
    if set(query) - {"q", "source", "batch", "page"} or any(
        len(query.getlist(key)) != 1 for key in query
    ):
        raise ValueError("invalid_parameters")
    page = query.get("page", "1")
    if re.fullmatch(r"[1-9][0-9]?", page) is None:
        raise ValueError("invalid_page")
    params = {key: query.get(key, "") for key in ("q", "source", "batch")}
    params["page"] = int(page)
    validate_query(**params)
    return params


def _hit_url(hit: SearchHit) -> str:
    if hit.case_key is None:
        return reverse("editorial_queue:index") + "?" + urlencode({"batch": hit.batch_id})
    url = reverse("editorial_workbench:detail", args=[hit.case_key])
    if hit.revision is not None:
        url += "?" + urlencode({"revision": hit.revision})
    return url + "#" + hit.anchor


def _exact(text: str) -> str:
    # Escape before marking safe; a wrapper preserves initial LF in <pre>,
    # and a CR entity avoids HTML parsing's CRLF-to-LF normalization.
    return mark_safe("<code>" + str(escape(text)).replace("\r", "&#13;") + "</code>")


def _reference_url(hit: SearchHit, params: dict) -> str | None:
    if hit.reference_ordinal is None:
        return None
    args = [hit.case_key]
    if hit.reference_origin == "revision":
        name = "editorial_search:revision_reference"
        args.append(hit.revision)
    else:
        name = "editorial_search:reference"
    args.append(hit.reference_ordinal)
    return reverse(name, args=args) + "?" + urlencode(params)


@require_safe
def search(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        params = _parameters(request)
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return _error(request, "معايير غير صالحة. استخدم بحثًا حتى ٨٠ حرفًا والمرشحات المتاحة.", 400)
    try:
        catalog = build_queue_catalog()
    except (WorkbenchDataError, HistoryDataError):
        return _error(request, "تعذر تحميل العينات بأمان. حاول مجددًا من صفحة البحث.", 503)
    try:
        result = search_catalog(catalog, **params)
    except ValueError:
        return _error(request, "الدفعة أو الصفحة غير متاحة لهذا البحث. ابدأ من الصفحة الأولى.", 400)

    def page_url(number):
        return reverse("editorial_search:index") + "?" + urlencode({**params, "page": number})

    response = render(
        request,
        "editorial_search/search.html",
        {
            "filters": params,
            "sources": SOURCE_TYPES,
            "batches": catalog.batches,
            "result": result,
            "rows": tuple(
                {
                    "hit": hit,
                    "url": _hit_url(hit),
                    "reference_url": _reference_url(hit, params),
                    "fields": tuple(
                        {"label": field.label, "text": _exact(field.text)} for field in hit.fields
                    ),
                }
                for hit in result.hits
            ),
            "previous_url": page_url(result.page - 1) if result.page > 1 else None,
            "next_url": page_url(result.page + 1) if result.page < result.pages else None,
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def reference(
    request: HttpRequest, key: str, ordinal: int, revision: int | None = None
) -> HttpResponse:
    local_only(request)
    try:
        params = _parameters(request)
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return _error(request, "معايير العودة إلى البحث غير صالحة.", 400)
    try:
        catalog = build_queue_catalog()
        card = reference_card(catalog, key, ordinal, revision)
        # Validate the return page/batch with the same bounded search contract.
        search_catalog(catalog, **params)
    except ReferenceNotFound:
        return _error(
            request, "الإحالة أو المراجعة غير موجودة. عد إلى البحث واختر نتيجة متاحة.", 404
        )
    except (WorkbenchDataError, HistoryDataError):
        return _error(request, "تعذر تحميل دليل الإحالة بأمان. أعد المحاولة من البحث.", 503)
    except ValueError:
        return _error(request, "الدفعة أو صفحة العودة غير متاحة. ابدأ من البحث مجددًا.", 400)
    result = bridge_reference(card.diagnostic) if card.diagnostic is not None else None
    workbench_url = reverse("editorial_workbench:detail", args=[key])
    if card.revision is not None:
        workbench_url += "?" + urlencode({"revision": card.revision})
    workbench_url += "#snapshot" if card.origin == "revision" else "#references"
    response = render(
        request,
        "editorial_search/reference.html",
        {
            "card": card,
            "source_text": _exact(card.source_text),
            "bridge": result,
            "return_url": reverse("editorial_search:index") + "?" + urlencode(params),
            "workbench_url": workbench_url,
            "triage_url": (
                reverse("reference_triage:detail", args=[key]) + f"#reference-{ordinal}"
                if card.origin == "diagnostic"
                else None
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
            return _error(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        payload = Path(__file__).with_name("search.css").read_bytes()
    except TooManyFieldsSent:
        return _error(request, "معايير غير صالحة.", 400)
    except OSError:
        return _error(request, "تعذر تحميل تنسيق البحث.", 503)
    response = HttpResponse(payload, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
