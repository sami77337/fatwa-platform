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
    MAX_SOURCE_ID,
    InvalidQuery,
    Page,
    bounded_int,
    strict_bool,
    validate_search,
)
from apps.reference.services import (
    CatalogUnavailable,
    HeadingNotFound,
    heading_path,
    list_books,
    node,
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


def _search_link(context: dict, offset: int, heading_id: int | None = None) -> str:
    # Rebuild only validated search fields; never copy arbitrary request parameters.
    params = {
        key: context[key]
        for key in ("query", "mode", "depth", "has_children", "root")
        if context[key] != ""
    }
    if "query" in params:
        params["q"] = params.pop("query")
    if offset:
        params["offset"] = offset
    fragment = "results-title"
    if heading_id is not None:
        params["heading"] = heading_id
        fragment = "reference-title"
    return reverse("home") + "?" + urlencode(params) + "#" + fragment


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
        "root": request.GET.get("root", ""),
    }
    try:
        if any(
            key not in {"q", "mode", "depth", "has_children", "offset", "root", "heading"}
            or len(values) != 1
            for key, values in request.GET.lists()
        ):
            raise InvalidQuery("Unknown or duplicate parameter")
        text, mode = context["query"], context["mode"]
        validate_search(text, mode)
        depth = bounded_int(context["depth"], 1, 5) if context["depth"] else None
        has_children = strict_bool(context["has_children"]) if context["has_children"] else None
        offset = bounded_int(request.GET.get("offset", "0"), 0, MAX_OFFSET)
        root_id = bounded_int(context["root"], 1, MAX_SOURCE_ID) if context["root"] else None
        heading_id = (
            bounded_int(request.GET["heading"], 1, MAX_SOURCE_ID)
            if "heading" in request.GET
            else None
        )
        if (
            not text.strip()
            and root_id is None
            and (depth or has_children is not None or "offset" in request.GET)
        ):
            raise InvalidQuery("Search text or source section required")
        books = list_books(Page(1))
        if books.total != 1:
            context["catalog_state"] = "multiple" if books.total else "empty"
        else:
            metadata = books.items[0]
            edition = resolve_edition(metadata["id"])
            if edition is None:
                raise CatalogUnavailable("Missing edition")
            section = None
            if root_id is not None:
                try:
                    heading = node(edition, root_id)
                except HeadingNotFound as error:
                    raise InvalidQuery("Unknown source section") from error
                if heading.parent_id is not None or heading.depth != 1:
                    raise InvalidQuery("Select a source root")
                section = {"id": root_id, "title": heading.title_original}
                context["root"] = str(root_id)
            root_page = roots(edition, Page(100))
            section_options = list(root_page.items)
            if section and not any(item["id"] == root_id for item in section_options):
                # A valid root beyond the first bounded root page remains selectable.
                section_options.append(section)
            context.update(
                {
                    "catalog_state": "available",
                    "source": metadata["work"]["title_original"],
                    "edition_id": metadata["id"],
                    "heading_count": metadata["heading_count"],
                    "roots": root_page,
                    "section": section,
                    "section_options": section_options,
                    "searching": bool(text.strip() or root_id or depth or has_children is not None),
                }
            )
            if context["searching"]:
                # Only an explicit source root permits browsing without search text.
                results = search(
                    edition,
                    text,
                    mode,
                    Page(30, offset),
                    depth=depth,
                    has_children=has_children,
                    **({"root_id": root_id} if root_id is not None else {}),
                )
                context.update(
                    results=results,
                    result_rows=[
                        {
                            "id": item["id"],
                            "title": item["title"],
                            "reference_url": _search_link(context, offset, item["id"]),
                        }
                        for item in results.items
                    ],
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
                    all_sections_url=(
                        _search_link({**context, "root": ""}, 0)
                        if text.strip()
                        else reverse("home")
                    ),
                )
            if heading_id is not None:
                try:
                    selected = node(edition, heading_id)
                    path = heading_path(edition, selected)
                    if root_id is not None and path[0]["id"] != root_id:
                        raise HeadingNotFound("Heading outside selected source section")
                except HeadingNotFound:
                    return _render_page(
                        request,
                        {
                            "current_page": "home",
                            "catalog_state": "invalid",
                            "error": "العنوان المطلوب غير متاح في هذا النطاق. عد إلى الفهرس واختر عنوانًا متاحًا.",
                        },
                        status=404,
                    )
                # A projection of validated reference metadata, never a model or private case.
                context["reference"] = {
                    "title": path[-1]["title"],
                    "part": path[-1]["part"],
                    "page": path[-1]["page"],
                    "path": [item["title"] for item in path],
                    "url": reverse("heading", args=[heading_id])
                    + "?"
                    + urlencode(
                        {
                            "basic": 1,
                            "edition": metadata["id"],
                        }
                    ),
                }
                context["reference_return_url"] = (
                    _search_link(context, offset)
                    if context["searching"]
                    else reverse("home") + "#roots-title"
                )
    except InvalidQuery:
        if context["catalog_state"] != "available":
            context["catalog_state"] = "invalid"
        context["error"] = (
            "تحقق من البحث: اكتب حتى ١٦٠ حرفًا وعشر كلمات، أو اختر بابًا متاحًا، واختر مرشحات صالحة."
        )
        return _render_page(request, context, status=400)
    except (DatabaseError, CatalogUnavailable, HeadingNotFound):
        context = {"current_page": "home", "catalog_state": "unavailable"}
    return _render_page(request, context)


@require_safe
def help_page(request: HttpRequest) -> HttpResponse:
    return _render_page(request, {"current_page": "help"})
