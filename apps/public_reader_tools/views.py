"""Explicit public reference save/share and current-authorized print/text copies."""

from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read

from . import services


def _query(request):
    if request.GET:
        raise preview.InvalidFilter()


def _page(request, template, context):
    response = render(request, template, context)
    response._allow_library_reader_tools = True
    return response


@safe_read
def reader(request, publication_id):
    _query(request)
    with services.reader_projection(publication_id) as result:
        return _page(request, "public_reader_tools/reader.html", result)


@safe_read
def descriptor(request, publication_id, *, action="SAVE_REFERENCE"):
    _query(request)
    with services.reader_projection(publication_id, action=action) as result:
        return JsonResponse(result["descriptor"])


@safe_read
def print_view(request, publication_id):
    _query(request)
    with services.reader_projection(publication_id, action="PRINT") as result:
        return _page(request, "public_reader_tools/print.html", result)


@safe_read
def download(request, publication_id):
    _query(request)
    with services.reader_projection(publication_id, action="DOWNLOAD_TEXT") as result:
        raw = services.text_copy(result)
        response = HttpResponse(raw, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="answer-{result["descriptor"]["publication_id"]}-v{result["descriptor"]["version"]}.txt"'
        )
        response["Content-Length"] = str(len(raw))
        return response


@safe_read
def saved(request):
    _query(request)
    services.enabled()
    return _page(request, "public_reader_tools/saved.html", {})


@safe_read
def asset(request, name):
    _query(request)
    services.enabled()
    if name not in {"tools.js", "tools.css"}:
        raise preview.PreviewUnavailable()
    raw = (Path(__file__).parent / "static" / "public_reader_tools" / name).read_bytes()
    return HttpResponse(
        raw,
        content_type="text/javascript; charset=utf-8"
        if name.endswith(".js")
        else "text/css; charset=utf-8",
    )
