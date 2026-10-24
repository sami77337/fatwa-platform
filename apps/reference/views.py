"""Public GET/HEAD interfaces. Method enforcement also covers missing URLs."""

from functools import wraps
from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.db import DatabaseError, connection
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_headers

from . import services
from .asset_integrity import (
    PINNED_PUBLIC_ASSET_MANIFEST,
    AssetIntegrityError,
    verified_reference_asset,
)
from .query import (
    MAX_OFFSET,
    MAX_SOURCE_ID,
    InvalidQuery,
    Page,
    bounded_int,
    strict_bool,
    validate_search,
)


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
        except (InvalidQuery, TooManyFieldsSent):
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
    _parameters(
        request, {"edition", "q", "mode", "limit", "offset", "root", "depth", "has_children"}
    )
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    page, requested = _page(request), _edition_id(request)
    root = request.GET.get("root")
    root_id = bounded_int(root, 1, MAX_SOURCE_ID) if root is not None else None
    depth = bounded_int(request.GET["depth"], 1, 5) if "depth" in request.GET else None
    has_children = (
        strict_bool(request.GET["has_children"]) if "has_children" in request.GET else None
    )
    edition = services.resolve_edition(requested)
    return _json(
        {
            **services.search(
                edition, text, mode, page, root_id, depth=depth, has_children=has_children
            ).as_dict(),
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
    allowed = {"edition", "q", "mode", "limit", "offset", "basic", "root", "depth", "has_children", "anchor"}
    if ident is not None:
        allowed.add("search_offset")
    _parameters(request, allowed)
    anchor_id = _anchor_id(request)
    if request.GET.get("basic", "1") != "1":
        raise InvalidQuery("Invalid basic navigation flag")
    text, mode = request.GET.get("q", ""), request.GET.get("mode", "normalized")
    validate_search(text, mode)
    depth_value = request.GET.get("depth", "")
    children_value = request.GET.get("has_children", "")
    root_value = request.GET.get("root", "")
    depth = bounded_int(depth_value, 1, 5) if depth_value else None
    has_children = strict_bool(children_value) if children_value else None
    root_id = bounded_int(root_value, 1, MAX_SOURCE_ID) if root_value else None
    page = _page(request)
    search_offset = (
        bounded_int(request.GET["search_offset"], 0, MAX_OFFSET)
        if "search_offset" in request.GET else None
    )
    requested = _edition_id(request)
    searching = "q" in request.GET or any(
        value is not None for value in (root_id, depth, has_children)
    )
    if ident is None and anchor_id is not None and (searching or "basic" not in request.GET):
        raise InvalidQuery("Root anchors require native browsing without search filters")
    books = services.list_books(Page(100))
    # A single edition needs no user choice; ambiguous content requests fail closed.
    selection_required = books.total > 1 and requested is None
    if selection_required and (ident is not None or searching or page.offset or anchor_id is not None):
        raise InvalidQuery("Select an edition explicitly")
    edition = services.resolve_edition(requested) if not selection_required else None
    context = {
        "books": books.items,
        "edition_selection_required": books.total > 1,
        "single_source": books.total == 1,
        "edition": services.edition_data(edition) if edition else None,
        "query": text,
        "searching": searching,
        "depth": depth_value,
        "depth_choices": range(1, 6),
        "has_children": children_value,
        "root": root_value,
        "mode": mode,
        "page": page,
        "anchor_id": anchor_id,
        "node": None,
        "ancestors": [],
        "pagination_url": request.path,
        "basic": (
            "basic" in request.GET or "limit" in request.GET or searching
            or page.offset > 0 or anchor_id is not None
        ),
    }
    if ident is not None:
        heading = services.node(edition, ident)
        context["node"] = services.heading_data(heading)
        context["ancestors"] = services.heading_path(edition, heading)
        context["results"] = services.child_page(edition, heading, page, anchor_id)
    elif searching:
        context["results"] = services.search(
            edition, text, mode, page, root_id, depth=depth, has_children=has_children
        )
    else:
        context["results"] = services.root_page(edition, page, anchor_id)
    results = context["results"]
    context["page"] = Page(results.limit, results.offset)
    context["previous_offset"] = max(0, results.offset - results.limit) if results.offset else None
    # Carry only validated search state through native detail/return links.
    # Child offsets and the search offset are independent.
    if searching and edition is not None:
        params = {"edition": edition.pk, "basic": "1", "q": text, "mode": mode}
        for key, value in (("root", root_value), ("depth", depth_value),
                           ("has_children", children_value)):
            if value:
                params[key] = value
        params["limit"] = page.limit
        params["offset"] = search_offset if search_offset is not None else page.offset
        context["search_return_url"] = reverse("catalog") + "?" + urlencode(params)
        context["search_offset"] = params["offset"]
    if edition is not None:
        navigation = {"edition": edition.pk}
        if context["basic"]:
            navigation.update({"basic": "1", "limit": page.limit})
        detail = dict(navigation)
        if searching:
            detail.update({"q": text, "mode": mode, "search_offset": context["search_offset"]})
            for key, value in (("root", root_value), ("depth", depth_value),
                               ("has_children", children_value)):
                if value:
                    detail[key] = value
        context["detail_query"] = "?" + urlencode(detail)
        if root_id is not None:
            unscoped = {key: value for key, value in detail.items()
                        if key not in {"root", "search_offset"}}
            context["clear_root_url"] = reverse("catalog") + "?" + urlencode(unscoped)
        ancestors = context["ancestors"]
        for index, ancestor in enumerate(ancestors[:-1]):
            child_id = ancestors[index + 1]["id"]
            params = {**detail, "basic": "1", "limit": page.limit, "anchor": child_id}
            ancestor["url"] = (
                reverse("heading", args=[ancestor["id"]]) + "?" + urlencode(params)
                + f"#heading-row-{child_id}"
            )
        root_params = dict(navigation)
        if ancestors:
            root_params.update({"basic": "1", "limit": page.limit, "anchor": ancestors[0]["id"]})
        context["roots_url"] = reverse("catalog") + "?" + urlencode(root_params)
        if ancestors:
            context["roots_url"] += f"#heading-row-{ancestors[0]['id']}"
            context["root_search_url"] = reverse("catalog") + "?" + urlencode({
                **navigation, "basic": "1", "root": ancestors[0]["id"], "limit": page.limit,
            })
        params = {**detail, "offset": 0}
        if ident is None:
            params.pop("search_offset", None)
        context["first_page_url"] = request.path + "?" + urlencode(params)
        context["page_empty"] = results.total > 0 and results.offset >= results.total
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
    except (InvalidQuery, TooManyFieldsSent):
        return render(
            request,
            "reference/error.html",
            {"message": "تحقق من معلمات البحث؛ يلزم تحديد الطبعة عند توفر أكثر من طبعة."},
            status=400,
        )
    except services.HeadingNotFound as error:
        params = {"basic": "1"}
        requested = _edition_id(request)
        if requested is not None and not isinstance(error, services.EditionNotFound):
            params = {"edition": requested, **params}
        return render(request, "reference/error.html", {
            "message": "العنوان المطلوب غير موجود في هذه الطبعة. يمكنك العودة إلى جذور الفهرس.",
            "catalog_url": reverse("catalog") + "?" + urlencode(params),
        }, status=404)
    except (DatabaseError, services.CatalogUnavailable):
        return render(
            request, "reference/error.html",
            {"retry_url": request.get_full_path()}, status=503
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
def public_asset(request: HttpRequest, asset: str) -> HttpResponse:
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
    # The five reference assets and the version-pinned htmx bundle are served
    # only after their exact bytes are verified. Other django_htmx JavaScript
    # remains separately allowlisted but unpinned.

    if asset in PINNED_PUBLIC_ASSET_MANIFEST:
        try:
            payload = verified_reference_asset(asset, filename)
        except AssetIntegrityError as exc:
            raise Http404("Unavailable or modified reference asset") from exc
        return HttpResponse(payload, content_type=content_type)
    return FileResponse(open(filename, "rb"), content_type=content_type)

# Wave7 endpoints are exported for E5's opt-in URLConf only. No legacy route is
# changed, and E2 owns the single workflow SSR screen consuming this context.
WORKFLOW_READ_KIND = 'WAVE7_SYNTHETIC_WORKFLOW'


def _workflow_json(data: dict, status=200):
    response = JsonResponse({'kind': WORKFLOW_READ_KIND, **data}, status=status,
                            json_dumps_params={'ensure_ascii': False})
    response['Cache-Control'] = 'no-store'
    return response


def _workflow_local_request(request):
    if not services._workflow_reads_enabled():
        raise services.WorkflowReadsDisabled()
    # Reuse the established development host+peer gate; no auth/session route.
    from apps.editorial_demo.views import local_only
    local_only(request)


def workflow_api_guard(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if request.method not in {'GET', 'HEAD'}:
            response = _workflow_json({'error': 'method_not_allowed'}, 405)
            response['Allow'] = 'GET, HEAD'
            return response
        try:
            _workflow_local_request(request)
            return view(request, *args, **kwargs)
        except services.WorkflowSearchScopeRequired:
            return _workflow_json({'error': 'search_scope_required'}, 400)
        except (InvalidQuery, TooManyFieldsSent):
            return _workflow_json({'error': 'invalid_query'}, 400)
        except (services.WorkflowReadsDisabled, services.WorkflowItemNotFound, Http404):
            return _workflow_json({'error': 'not_found'}, 404)
        except (services.WorkflowReadUnavailable, DatabaseError):
            return _workflow_json({'error': 'workflow_unavailable'}, 503)
    return guarded


def _workflow_read_query(request, *, batches=False):
    allowed = {'q', 'mode', 'intake_status', 'review_status', 'limit', 'offset'}
    if not batches:
        allowed.add('batch')
    _parameters(request, allowed)
    batch = request.GET.get('batch') or None
    text, mode = request.GET.get('q', ''), request.GET.get('mode', 'normalized')
    intake_status = request.GET.get('intake_status') or None
    review_status = request.GET.get('review_status') or None
    page = Page(bounded_int(request.GET.get('limit', '20'), 1, 100),
                bounded_int(request.GET.get('offset', '0'), 0, MAX_OFFSET))
    batch = services._workflow_filters(text, mode, intake_status, review_status, page, batch)
    return {'batch_id': batch, 'text': text, 'mode': mode,
            'intake_status': intake_status, 'review_status': review_status, 'page': page}


@workflow_api_guard
def api_workflow_items(request):
    result = services.workflow_items(**_workflow_read_query(request), synthetic_fixtures_only=True)
    return _workflow_json(result.as_dict())


@workflow_api_guard
def api_workflow_batches(request):
    query = _workflow_read_query(request, batches=True)
    query.pop('batch_id')
    result = services.workflow_batches(**query, synthetic_fixtures_only=True)
    return _workflow_json(result.as_dict())


@workflow_api_guard
def api_workflow_item(request, ident):
    _parameters(request, {'batch'})
    batch = request.GET.get('batch') or None
    result = services.workflow_item(ident, batch_id=batch, synthetic_fixtures_only=True)
    return _workflow_json(result.as_dict())


def workflow_read_context(request, *, item_id=None) -> dict:
    """E2 SSR data/return state using the JSON reader's exact query contract.

    No template, duplicate UI, route or arbitrary return URL here. E2 combines
    the returned query strings with its own named list/detail routes.
    """
    if request.method not in {'GET', 'HEAD'}:
        raise Http404
    _workflow_local_request(request)
    query = _workflow_read_query(request)
    params = {'q': query['text'], 'mode': query['mode'],
              'limit': query['page'].limit, 'offset': query['page'].offset}
    for key, value in (('batch', query['batch_id']), ('intake_status', query['intake_status']),
                       ('review_status', query['review_status'])):
        if value is not None:
            params[key] = str(value)
    result, detail = None, None
    if item_id is None:
        result = services.workflow_items(**query, synthetic_fixtures_only=True)
    else:
        detail = services.workflow_item(item_id, batch_id=query['batch_id'], synthetic_fixtures_only=True)
    previous = (max(0, result.offset-result.limit) if result is not None and result.offset else None)
    following = result.next_offset if result is not None else None
    return {'workflow_page': result, 'workflow_item': detail,
            'workflow_query': query['text'], 'workflow_mode': query['mode'],
            'workflow_batch': str(query['batch_id']) if query['batch_id'] is not None else '',
            'workflow_intake_status': query['intake_status'] or '',
            'workflow_review_status': query['review_status'] or '',
            'workflow_limit': query['page'].limit, 'workflow_offset': query['page'].offset,
            'workflow_filter_query': urlencode(params), 'workflow_return_query': urlencode(params),
            'workflow_previous_query': urlencode({**params, 'offset': previous}) if previous is not None else None,
            'workflow_next_query': urlencode({**params, 'offset': following}) if following is not None else None}
