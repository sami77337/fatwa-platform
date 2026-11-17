"""Bounded, read-only SSR entry points; no catalog mutations."""

from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.reference.query import (
    MAX_OFFSET,
    InvalidQuery,
    Page,
    bounded_int,
    strict_bool,
    validate_search,
)
from apps.reference.services import (
    CatalogUnavailable,
    HeadingNotFound,
    list_books,
    resolve_edition,
    roots,
    search,
)

_PAGES = {
    "home": ("الرئيسية | الفهرس الفقهي", "تصفّح أبواب المرجع الفقهي وابحث في عناوينه."),
    "help": (
        "دليل الاستخدام والمصدر | الفهرس الفقهي",
        "دليل تصفّح عناوين المرجع الفقهي والبحث فيها وتوثيق مواضعها.",
    ),
}
_validate_https = URLValidator(schemes=["https"])


def _public_origin() -> str:
    # The final domain is an owner decision. Request headers never select it.
    value = getattr(settings, "PUBLIC_SITE_ORIGIN", None)
    if not isinstance(value, str) or not value:
        return ""
    try:
        _validate_https(value)
        parts = urlsplit(value)
        port = parts.port  # urlsplit defers port validation until access.
    except (ValidationError, ValueError):
        return ""
    if (
        port == 0
        or parts.username is not None
        or value.removesuffix("/") != f"https://{parts.netloc}"
    ):
        return ""
    return f"https://{parts.netloc}"


def _render_page(request: HttpRequest, context: dict, *, status: int = 200) -> HttpResponse:
    page = context["current_page"]
    context["page_title"], context["page_description"] = _PAGES[page]
    # Search input can contain personal text. Only the clean homepage and the
    # fixed source guide represent shareable public page identities.
    shareable = page == "help" or (
        not request.GET and context.get("catalog_state") != "unavailable"
    )
    context["withhold_preview"] = status != 200 or not shareable
    if not context["withhold_preview"]:
        origin = _public_origin()
        if origin:
            context["canonical_url"] = origin + reverse("public_help" if page == "help" else "home")
    response = render(request, f"public_site/{page}.html", context, status=status)
    if context["withhold_preview"]:
        response["X-Robots-Tag"] = "noindex, nosnippet"
    return response


def _search_link(context: dict, offset: int) -> str:
    # Rebuild only validated search fields; never copy arbitrary request parameters.
    params = {
        key: context[key]
        for key in ("query", "mode", "depth", "has_children")
        if context[key] != ""
    }
    params["q"] = params.pop("query")
    if offset:
        params["offset"] = offset
    return reverse("home") + "?" + urlencode(params) + "#results-title"


@require_safe
def home(request: HttpRequest) -> HttpResponse:
    context: dict[str, object] = {
        "current_page": "home",
        "catalog_state": "unavailable",
        "source": None,
        "query": request.GET.get("q", ""),
        "mode": request.GET.get("mode", "normalized"),
        "depth": request.GET.get("depth", ""),
        "has_children": request.GET.get("has_children", ""),
    }
    try:
        if any(
            key not in {"q", "mode", "depth", "has_children", "offset"} or len(values) != 1
            for key, values in request.GET.lists()
        ):
            raise InvalidQuery("Unknown or duplicate parameter")
        text, mode = context["query"], context["mode"]
        validate_search(text, mode)
        depth = bounded_int(context["depth"], 1, 5) if context["depth"] else None
        has_children = strict_bool(context["has_children"]) if context["has_children"] else None
        offset = bounded_int(request.GET.get("offset", "0"), 0, MAX_OFFSET)
        if not text.strip() and (depth or has_children is not None or "offset" in request.GET):
            raise InvalidQuery("Search text required")
        books = list_books(Page(1))
        if books.total != 1:
            context["catalog_state"] = "multiple" if books.total else "empty"
        else:
            metadata = books.items[0]
            edition = resolve_edition(metadata["id"])
            if edition is None:
                raise CatalogUnavailable("Missing edition")
            root_page = roots(edition, Page(100))
            context.update(
                {
                    "catalog_state": "available",
                    "source": metadata["work"]["title_original"],
                    "edition_id": metadata["id"],
                    "heading_count": metadata["heading_count"],
                    "roots": root_page,
                    "searching": bool(text.strip() or depth or has_children is not None),
                }
            )
            if context["searching"]:
                # The homepage keeps text required, even with filters or pagination.
                results = search(
                    edition,
                    text,
                    mode,
                    Page(30, offset),
                    depth=depth,
                    has_children=has_children,
                )
                context.update(
                    results=results,
                    result_start=offset + 1 if results.items else 0,
                    result_end=offset + len(results.items),
                    first_results_url=_search_link(context, 0) if offset else "",
                    previous_results_url=(
                        _search_link(context, max(0, offset - 30)) if offset else ""
                    ),
                    next_results_url=(
                        _search_link(context, results.next_offset)
                        if results.next_offset is not None
                        else ""
                    ),
                    search_limit_reached=(
                        bool(results.items)
                        and results.next_offset is None
                        and offset + len(results.items) < results.total
                    ),
                )
    except InvalidQuery:
        if context["catalog_state"] != "available":
            context["catalog_state"] = "invalid"
        context["error"] = "تحقق من البحث: اكتب حتى ١٦٠ حرفًا وعشر كلمات، واختر مرشحات صالحة."
        return _render_page(request, context, status=400)
    except (DatabaseError, CatalogUnavailable, HeadingNotFound):
        context = {"current_page": "home", "catalog_state": "unavailable"}
    return _render_page(request, context)


@require_safe
def help_page(request: HttpRequest) -> HttpResponse:
    return _render_page(request, {"current_page": "help"})
