"""Public GET/HEAD interfaces. Method enforcement also covers missing URLs."""

from functools import wraps

from django.db import DatabaseError, connection
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_headers

from . import services
from .query import MAX_OFFSET, MAX_SOURCE_ID, InvalidQuery, Page, bounded_int, validate_search


def _parameters(request: HttpRequest, allowed: set[str]) -> None:
    if any(key not in allowed or len(values) != 1 for key, values in request.GET.lists()):
        raise InvalidQuery("Unknown or duplicate query parameter")


def _edition_id(request: HttpRequest) -> int | None:
    value = request.GET.get("edition")
    return bounded_int(value, 1, MAX_SOURCE_ID) if value is not None else None


def _page(request: HttpRequest) -> Page:
    return Page(
        bounded_int(request.GET.get("limit", "30"), 1, 100),
        bounded_int(request.GET.get("offset", "0"), 0, MAX_OFFSET),
    )


def _anchor_id(request: HttpRequest) -> int | None:
    if "anchor" in request.GET and "offset" in request.GET:
        raise InvalidQuery("Anchor and offset are mutually exclusive")
    value = request.GET.get("anchor")
    return bounded_int(value, 1, MAX_SOURCE_ID) if value is not None else None


def _json(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(
        {"kind": services.KIND, **data},
        status=status,
        json_dumps_params={
            "ensure_ascii": False,
        },
    )


def api_guard(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if request.method not in {"GET", "HEAD"}:
            response = _json({"error": "method_not_allowed"}, 405)
            response["Allow"] = "GET, HEAD"
            return response
        try:
            return view(request, *args, **kwargs)
        except InvalidQuery:
            return _json({"error": "invalid_query"}, 400)
        except services.HeadingNotFound:
            return _json({"error": "not_found"}, 404)
        except (DatabaseError, services.CatalogUnavailable):
            return _json({"error": "catalog_unavailable"}, 503)

    return guarded


@api_guard
def api_books(request: HttpRequest) -> JsonResponse:
    _parameters(request, {"limit", "offset"})
    return _json(services.list_books(_page(request)).as_dict())


@api_guard
def api_roots(request: HttpRequest) -> JsonResponse:
    _parameters(request, {"edition", "limit", "offset"})
    page, requested = _page(request), _edition_id(request)
    edition = services.resolve_edition(requested)
    return _json(
        {
            **services.roots(edition, page).as_dict(),
            "edition": services.edition_data(edition) if edition else None,
        }
    )


@api_guard
def api_node(request: HttpRequest, ident: int) -> JsonResponse:
    _parameters(request, {"edition"})
    edition = services.resolve_edition(_edition_id(request))
    heading = services.node(edition, ident)
    return _json(
        {
            "node": services.heading_data(heading),
            "ancestors": services.heading_path(edition, heading),
            "edition": services.edition_data(edition),
        }
    )


@api_guard
def api_children(request: HttpRequest, ident: int) -> JsonResponse:
    _parameters(request, {"edition", "limit", "offset", "anchor"})
    page, requested, anchor_id = _page(request), _edition_id(request), _anchor_id(request)
    edition = services.resolve_edition(requested)
    heading = services.node(edition, ident)
    return _json(
        {
            **services.child_page(edition, heading, page, anchor_id).as_dict(),
            "parent": ident,
            "edition": services.edition_data(edition),
        }
    )


@api_guard
def api_search(request: HttpRequest) -> JsonResponse:
    _parameters(request, {"edition", "q", "mode", "limit", "offset", "root"})
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    page, requested = _page(request), _edition_id(request)
    root = request.GET.get("root")
    root_id = bounded_int(root, 1, MAX_SOURCE_ID) if root is not None else None
    edition = services.resolve_edition(requested)
    return _json(
        {
            **services.search(edition, text, mode, page, root_id).as_dict(),
            "query": text,
            "mode": mode,
            "edition": services.edition_data(edition) if edition else None,
        }
    )


@api_guard
def health(request: HttpRequest) -> JsonResponse:
    _parameters(request, set())
    # Liveness only: no database readiness or gate acceptance is implied.
    return _json({"alive": True, "read_only": True})


@api_guard
def status(request: HttpRequest) -> JsonResponse:
    _parameters(request, set())
    return _json(
        {
            "read_only": True,
            "sensitive_write_routes_enabled": False,
            "fatwa_publications_available": False,
            "deployment": "NOT_DEPLOYED",
            "gates": "GATES_HOLD",
            "editions": services.list_books(Page(100)).as_dict(),
        }
    )


@api_guard
def ready(request: HttpRequest) -> JsonResponse:
    _parameters(request, set())
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    # Also verify that the required migrated schema is reachable.
    services.list_books(Page(1))
    return _json({"database_reachable": True})


def _html_context(request: HttpRequest, ident: int | None = None) -> dict:
    allowed = {"edition", "q", "mode", "limit", "offset", "basic"}
    if ident is not None:
        allowed.add("anchor")
    _parameters(request, allowed)
    anchor_id = _anchor_id(request)
    if request.GET.get("basic", "1") != "1":
        raise InvalidQuery("Invalid basic navigation flag")
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    page = _page(request)
    requested = _edition_id(request)
    books = services.list_books(Page(100))
    # A single edition needs no user choice; ambiguous content requests fail closed.
    selection_required = books.total > 1 and requested is None
    if selection_required and (ident is not None or text.strip() or page.offset):
        raise InvalidQuery("Select an edition explicitly")
    edition = services.resolve_edition(requested) if not selection_required else None
    context = {
        "books": books.items,
        "edition_selection_required": books.total > 1,
        "single_source": books.total == 1,
        "edition": services.edition_data(edition) if edition else None,
        "query": text,
        "mode": mode,
        "page": page,
        "node": None,
        "ancestors": [],
        "pagination_url": request.path,
        "basic": (
            "basic" in request.GET or bool(text.strip()) or page.offset > 0 or anchor_id is not None
        ),
    }
    if ident is not None:
        heading = services.node(edition, ident)
        context["node"] = services.heading_data(heading)
        context["ancestors"] = services.heading_path(edition, heading)
        context["results"] = services.child_page(edition, heading, page, anchor_id)
    elif text.strip():
        context["results"] = services.search(edition, text, mode, page)
    else:
        context["results"] = services.roots(edition, page)
    results = context["results"]
    context["page"] = Page(results.limit, results.offset)
    context["previous_offset"] = max(0, results.offset - results.limit) if results.offset else None
    return context


@require_safe
@vary_on_headers("HX-Request")
def catalog(request: HttpRequest, ident: int | None = None) -> HttpResponse:
    try:
        context = _html_context(request, ident)
        template = (
            "reference/catalog_content.html"
            if request.headers.get("HX-Request") == "true"
            else "reference/catalog.html"
        )
        return render(request, template, context)
    except InvalidQuery:
        return render(
            request,
            "reference/error.html",
            {"message": "تحقق من معلمات البحث؛ يلزم تحديد الطبعة عند توفر أكثر من طبعة."},
            status=400,
        )
    except services.HeadingNotFound as error:
        raise Http404("Unknown reference heading") from error
    except (DatabaseError, services.CatalogUnavailable):
        return render(
            request, "reference/error.html", {"message": "فهرس المرجع غير متاح حاليًا."}, status=503
        )


@require_safe
@vary_on_headers("HX-Request")
def branch(request: HttpRequest, ident: int) -> HttpResponse:
    # Normal navigation always includes title/citation/breadcrumb context.
    if request.headers.get("HX-Request") != "true":
        return catalog(request, ident)
    try:
        context = _html_context(request, ident)
        return render(request, "reference/heading_list.html", context)
    except InvalidQuery:
        return HttpResponse("معلمات غير صالحة", status=400)
    except services.HeadingNotFound as error:
        raise Http404("Unknown reference heading") from error
    except (DatabaseError, services.CatalogUnavailable):
        return HttpResponse("الفهرس غير متاح", status=503)


@require_safe
def public_asset(request: HttpRequest, asset: str) -> FileResponse:
    from django.contrib.staticfiles import finders

    allowed = asset in {
        "reference/style.css",
        "reference/tree.js",
        "reference/catalog.css",
        "reference/catalog.js",
        "reference/django-api.mjs",
    } or (
        asset.startswith("django_htmx/")
        and asset.endswith(".js")
        and ".." not in asset
        and "\\" not in asset
    )
    if not allowed:
        raise Http404("Unknown asset")
    filename = finders.find(asset)
    if not filename:
        raise Http404("Missing installed asset")
    content_type = (
        "text/css; charset=utf-8" if asset.endswith(".css") else "text/javascript; charset=utf-8"
    )
    return FileResponse(open(filename, "rb"), content_type=content_type)
