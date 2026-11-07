"""One authenticated read receipt on an isolated synthetic development server."""

import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import path
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe
from django.views.static import serve

from apps.editorial_demo.views import local_only
from apps.fast9_case_source_join.draft_source_review import inspect_draft_source
from apps.fast9_case_source_join.source_journal import (
    ReviewConflict,
    acknowledge_review,
    history_digest,
    read_review_state,
)

from .source_review import CASE_KEY, DRAFT_REVISION, KINDS, STATUS, reading_state
from .source_review_identity import authenticate_fixture_reviewer
from .views import _packet_exact, _source_journal_directory

TEMPLATE = "editorial_workbench/reviewer_desk.html"
DESK_SETTINGS = "apps.editorial_workbench.reviewer_settings"


class DeskGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        local_only(request)
        if settings.SETTINGS_MODULE != DESK_SETTINGS:
            raise Http404
        methods = ("GET", "HEAD", "POST") if request.path == "/review/" else ("GET", "HEAD")
        response = (
            self.get_response(request)
            if request.method in methods
            else HttpResponseNotAllowed(methods)
        )
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        return response


@sensitive_post_parameters("token")
@require_http_methods(["GET", "HEAD", "POST"])
def reviewer_desk(request):
    directory = _source_journal_directory()

    def failure(message, status):
        return render(request, TEMPLATE, {"message": message}, status=status)

    if request.META.get("QUERY_STRING"):
        return failure("افتح رابط مكتب المراجعة دون معاملات إضافية.", 400)
    if directory is None:
        return failure("تعذّر فتح مجلد سجل التدريب.", 503)

    status = 200
    message = ""
    if request.method == "POST":
        if request.content_type != "application/x-www-form-urlencoded":
            return failure("استخدم نموذج تسجيل القراءة المعروض في المكتب.", 415)
        try:
            fields = request.POST
            names = {"count", "source_digest", "draft_digest", "token"}
            if (
                set(fields) - {"csrfmiddlewaretoken"} != names
                or any(len(fields.getlist(k)) != 1 for k in fields)
                or not re.fullmatch(r"[1-9][0-9]{0,2}", fields["count"])
                or int(fields["count"]) > 128
                or not all(
                    re.fullmatch(r"[0-9a-f]{64}", fields[k])
                    for k in ("source_digest", "draft_digest")
                )
            ):
                return failure("تعذّر تحديد نسخة السؤال من النموذج.", 400)
        except SuspiciousOperation:
            return failure("تعذّرت قراءة النموذج.", 400)
        try:
            reviewer = authenticate_fixture_reviewer(fields["token"])
        except ValueError:
            return failure("تعذّر التحقق من رمز المراجع. ارجع وأعد إدخال الرمز.", 403)
        try:
            acknowledge_review(
                directory,
                reviewer=reviewer,
                count=int(fields["count"]),
                source_digest=fields["source_digest"],
                draft_digest=fields["draft_digest"],
                synthetic_fixtures_only=True,
            )
        except ReviewConflict:
            status = 409
            message = "تغيّر السؤال أو المسودة قبل حفظ القراءة. راجع النسخة المعروضة ثم سجّل قراءتك."
        except (ValueError, OSError):
            return failure("تعذّر التحقق من سجل التدريب أو حفظ القراءة.", 503)
        else:
            return HttpResponse(status=303, headers={"Location": "/review/"})

    try:
        events, receipt = read_review_state(directory, synthetic_fixtures_only=True)
        if not events:
            return failure("لا توجد أحداث محفوظة لهذه القضية في سجل التدريب.", 404)
        observation = inspect_draft_source(
            CASE_KEY, DRAFT_REVISION, events, synthetic_fixtures_only=True
        )
    except (ValueError, OSError):
        return failure("تعذّرت قراءة سجل السؤال والقراءات المسجّلة.", 503)

    digest = history_digest(events)
    reviewed_count = receipt.count if receipt else 0
    state = reading_state(receipt, len(events), observation.draft_revision_sha256)

    timeline = [
        {
            "number": i,
            "label": KINDS[e.kind],
            "is_new": i > reviewed_count,
            "body": _packet_exact(e.body_utf8.decode()) if e.body_utf8 is not None else None,
        }
        for i, e in enumerate(events, 1)
    ]
    return render(
        request,
        TEMPLATE,
        {
            "case_key": CASE_KEY,
            "revision": DRAFT_REVISION,
            "current_count": len(events),
            "source_digest": digest,
            "draft_digest": observation.draft_revision_sha256,
            "source_status": STATUS[observation.status],
            "original": timeline[0]["body"],
            "latest": timeline[-1]["body"],
            "events": timeline,
            "reviewed_count": reviewed_count,
            "review_state": state,
            "recorded_at": datetime.fromisoformat(receipt.recorded_at) if receipt else None,
            "message": message,
            "can_ack": True,
        },
        status=status,
    )


urlpatterns = [
    path("review/", reviewer_desk, name="reviewer_desk"),
    path(
        "dev/editorial-workbench/style.css",
        require_safe(serve),
        {"path": "workbench.css", "document_root": Path(__file__).parent},
    ),
]
