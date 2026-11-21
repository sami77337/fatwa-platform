"""Read-only SSR navigation. No anonymous access to staff/transcript APIs."""

from pathlib import Path
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.public_answer_media.navigation import publication_recordings_url
from apps.public_reader_tools.navigation import publication_tools_url

from . import fatwa_references, services
from .guard import safe_read
from .navigation import teaching_catalog_url


def _knowledge_url(publication_id=None):
    if (
        not apps.is_installed("apps.public_knowledge")
        or getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ENABLED", False) is not True
    ):
        return ""
    return (
        reverse("public_knowledge:publication", args=[publication_id, "ar"])
        if publication_id
        else reverse("public_knowledge:index")
    )


def _filters(request):
    if set(request.GET) - {"q", "category", "material", "page"} or any(
        len(values) != 1 for _, values in request.GET.lists()
    ):
        raise services.InvalidFilter()
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        raise services.InvalidFilter() from None
    return services.filters(
        query=request.GET.get("q", ""),
        category=request.GET.get("category", ""),
        material=request.GET.get("material", ""),
        page=page,
    )


def _query(filters, **overrides):
    return urlencode(
        {
            "q": filters["query"],
            "category": filters["category"],
            "material": filters["material"],
            "page": filters["page"],
            **overrides,
        }
    )


def _navigation(filters):
    return {
        "filters": filters,
        "return_url": reverse("library_preview:index") + "?" + _query(filters),
    }


def _source_url(publication_id, position, filters):
    return (
        reverse("library_preview:source", args=[publication_id, position]) + "?" + _query(filters)
    )


@safe_read
def index(request):
    chosen = _filters(request)
    result = services.browse(**chosen)
    for row in result["items"]:
        row["url"] = reverse("library_preview:detail", args=[row["id"]]) + "?" + _query(chosen)
    result.update(_navigation(chosen))
    result["knowledge_url"] = _knowledge_url()
    result["teaching_url"] = teaching_catalog_url()
    result["reference_lookup_enabled"] = fatwa_references.enabled()
    result["previous_url"] = "?" + _query(chosen, page=chosen["page"] - 1)
    result["next_url"] = "?" + _query(chosen, page=chosen["page"] + 1)
    return render(request, "library_preview/index.html", result)


@safe_read
def detail(request, publication_id):
    chosen = _filters(request)
    if fatwa_references.optional_grant(publication_id) is not None:
        with fatwa_references.projection(publication_id=publication_id) as result:
            return _detail(request, publication_id, chosen, **result)
    edition = services.read(str(publication_id))
    return _detail(request, publication_id, chosen, edition=edition)


def _detail(request, publication_id, chosen, *, edition, fatwa_reference=""):
    for source in edition["references"] + edition["relations"]["references"]:
        source["url"] = _source_url(publication_id, source["position"], chosen)
    return render(
        request,
        "library_preview/detail.html",
        {
            "edition": edition,
            "fatwa_reference": fatwa_reference,
            "knowledge_url": _knowledge_url(publication_id),
            "recordings_url": publication_recordings_url(publication_id),
            "reader_tools_url": publication_tools_url(publication_id),
            **_navigation(chosen),
        },
    )


@safe_read
def by_reference(request):
    if set(request.GET) != {"ref"} or len(request.GET.getlist("ref")) != 1:
        raise services.InvalidFilter()
    with fatwa_references.projection(reference=request.GET["ref"]) as result:
        return _detail(request, result["edition"]["id"], services.filters(), **result)


@safe_read
def source(request, publication_id, position):
    chosen = _filters(request)
    result = services.read_reference(str(publication_id), position)
    result.update(_navigation(chosen))
    result["publication_url"] = (
        reverse("library_preview:detail", args=[publication_id]) + "?" + _query(chosen)
    )
    return render(request, "library_preview/source.html", result)


@safe_read
def stylesheet(request):
    if request.GET:
        raise services.InvalidFilter()
    body = (Path(__file__).parent / "static/library_preview/preview.css").read_text()
    return HttpResponse(body, content_type="text/css; charset=utf-8")
