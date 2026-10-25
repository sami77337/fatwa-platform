"""Loopback-only downloads of complete fixed synthetic export bundles."""

from hashlib import sha256

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only

from .services import ExportError, build_export

_FILENAMES = ("report.json", "cases.csv", "batches.csv", "manifest.json")


def _private(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _failure(message: str, status: int) -> HttpResponse:
    return _private(HttpResponse(message, status=status, content_type="text/plain; charset=utf-8"))


@require_safe
def index(request: HttpRequest) -> HttpResponse:
    local_only(request)
    if request.META.get("QUERY_STRING", ""):
        return _failure("لا يقبل التصدير الاصطناعي معاملات إضافية.", 400)
    try:
        bundle = build_export(synthetic_fixtures_only=True)
        report = bundle.report()
    except ExportError:
        return _failure("تعذر إنشاء التصدير الاصطناعي الكامل بأمان.", 503)
    files = tuple(
        {
            "filename": name,
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
            "url": reverse("editorial_export:download", args=[name]),
        }
        for name, payload in bundle.files
    )
    return _private(
        render(
            request,
            "editorial_export/index.html",
            {
                "report": report,
                "files": files,
                "case_count": len(report["cases"]),
                "batch_count": len(report["batches"]),
            },
        )
    )


@require_safe
def download(request: HttpRequest, filename: str) -> HttpResponse:
    local_only(request)
    if filename not in _FILENAMES:
        raise Http404
    if request.META.get("QUERY_STRING", ""):
        return _failure("لا يقبل التصدير الاصطناعي معاملات إضافية.", 400)
    try:
        payload = build_export(synthetic_fixtures_only=True).file(filename)
    except ExportError:
        return _failure("تعذر إنشاء التصدير الاصطناعي الكامل بأمان.", 503)
    content_type = "text/csv" if filename.endswith(".csv") else "application/json"
    response = _private(HttpResponse(payload, content_type=content_type + "; charset=utf-8"))
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Export-SHA256"] = sha256(payload).hexdigest()
    return response
