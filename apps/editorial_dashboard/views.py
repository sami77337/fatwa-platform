"""Guard access and query bounds before reading fixed synthetic data."""

from pathlib import Path

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_workbench.services import WorkbenchDataError
from apps.fatwa_drafts.intake import ValidationError
from apps.revision_core.revision_history import HistoryDataError

from .services import UnknownBatch, build_dashboard


def _failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(
        request, "editorial_dashboard/error.html", {"message": message}, status=status
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def dashboard(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        query = request.GET
        batch_id = query.get("batch", "")
        if (
            set(query) - {"batch"}
            or any(len(query.getlist(key)) != 1 for key in query)
            or len(batch_id) > 100
            or any(not (c.isascii() and (c.isalnum() or c == "-")) for c in batch_id)
        ):
            raise ValueError
    except (ValueError, TooManyFieldsSent):
        return _failure(request, "معيار غير صالح. اختر الدفعة من القائمة.", 400)
    try:
        report = build_dashboard(batch_id)
    except UnknownBatch:
        return _failure(request, "الدفعة غير معروفة. عد إلى جميع الدفعات.", 400)
    except (WorkbenchDataError, HistoryDataError, ValidationError):
        return _failure(request, "تعذر تحميل المؤشرات بأمان. عد إلى اللوحة وأعد المحاولة.", 503)
    response = render(
        request,
        "editorial_dashboard/dashboard.html",
        {
            "dashboard": report,
            "batch_id": batch_id,
            "batches": tuple(item["batch"] for item in report.batches),
            "dashboard_url": reverse("editorial_dashboard:index"),
            "queue_url": reverse("editorial_queue:index"),
            "investigation_url": reverse("reference_triage:index"),
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.GET:
            return _failure(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        content = Path(__file__).with_name("dashboard.css").read_bytes()
    except TooManyFieldsSent:
        return _failure(request, "معايير غير صالحة.", 400)
    except OSError:
        return _failure(request, "تعذر تحميل التنسيق المحلي. أعد المحاولة.", 503)
    response = HttpResponse(content, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
