"""Public GET/HEAD interfaces. Method enforcement also covers missing URLs."""

from functools import wraps

from django.db import DatabaseError, connection
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
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
    edition = services.resolve_edition(_edition_id(request))
    return _json(
        {
            **services.roots(edition, _page(request)).as_dict(),
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
    if "anchor" in request.GET and "offset" in request.GET:
        raise InvalidQuery("Anchor and offset are mutually exclusive")
    anchor = request.GET.get("anchor")
    anchor_id = bounded_int(anchor, 1, MAX_SOURCE_ID) if anchor is not None else None
    edition = services.resolve_edition(_edition_id(request))
    heading = services.node(edition, ident)
    return _json(
        {
            **services.child_page(edition, heading, _page(request), anchor_id).as_dict(),
            "parent": ident,
            "edition": services.edition_data(edition),
        }
    )


@api_guard
def api_search(request: HttpRequest) -> JsonResponse:
    _parameters(request, {"edition", "q", "mode", "limit", "offset", "root"})
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    edition = services.resolve_edition(_edition_id(request))
    root = request.GET.get("root")
    root_id = bounded_int(root, 1, MAX_SOURCE_ID) if root is not None else None
    return _json(
        {
            **services.search(edition, text, mode, _page(request), root_id).as_dict(),
            "query": text,
            "mode": mode,
            "edition": services.edition_data(edition) if edition else None,
        }
    )


def health(request: HttpRequest) -> JsonResponse:
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


def ready(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        # Also verify that the required migrated schema is reachable.
        services.list_books(Page(1))
        return _json({"database_reachable": True})
    except DatabaseError:
        return _json({"error": "catalog_unavailable"}, 503)


def _html_context(request: HttpRequest, ident: int | None = None) -> dict:
    allowed = {"edition", "q", "mode", "limit", "offset", "basic"}
    _parameters(request, allowed)
    if request.GET.get("basic", "1") != "1":
        raise InvalidQuery("Invalid basic navigation flag")
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    page = _page(request)
    books = services.list_books(Page(100))
    requested = _edition_id(request)
    # An ambiguous catalog presents an edition chooser before querying headings.
    edition = services.resolve_edition(requested) if requested or books.total <= 1 else None
    context = {
        "books": books.items,
        "edition": services.edition_data(edition) if edition else None,
        "query": text,
        "mode": mode,
        "page": page,
        "node": None,
        "ancestors": [],
        "pagination_url": request.path,
        "basic": "basic" in request.GET or bool(text.strip()) or page.offset > 0,
    }
    if ident is not None:
        heading = services.node(edition, ident)
        context["node"] = services.heading_data(heading)
        context["ancestors"] = services.heading_path(edition, heading)
        context["results"] = services.children(edition, heading, page)
    elif text.strip():
        context["results"] = services.search(edition, text, mode, page)
    else:
        context["results"] = services.roots(edition, page)
    context["previous_offset"] = max(0, page.offset - page.limit) if page.offset else None
    return context


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
            {"message": "تحقق من معلمات البحث واختر الطبعة."},
            status=400,
        )
    except services.HeadingNotFound as error:
        raise Http404("Unknown reference heading") from error
    except (DatabaseError, services.CatalogUnavailable):
        return render(
            request, "reference/error.html", {"message": "فهرس المرجع غير متاح حاليًا."}, status=503
        )


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
