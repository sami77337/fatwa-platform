"""Optional local adapter: existing guarded Wave7 reads, never a synthetic seed."""

import re
from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_demo.workflow_audit import AuditDataError, build_audit_timeline
from apps.intake_workflow import contracts as c
from apps.intake_workflow import guards, review
from apps.reference import services

from .views import failure


def _positive(value: str, maximum: int) -> int:
    if re.fullmatch(r"[1-9][0-9]{0,4}", value) is None or int(value) > maximum:
        raise ValueError("invalid_page")
    return int(value)


@require_safe
def stored_audit(request: HttpRequest) -> HttpResponse:
    local_only(request)
    if not services._workflow_reads_enabled():
        return failure(
            request,
            "التدقيق المحفوظ غير مفعّل. يتطلب إعداد Wave7 المحلي وحواجز قاعدة البيانات الاصطناعية القائمة. يمكنك متابعة العينات الثابتة من القائمة.",
            404,
        )
    try:
        query = request.GET
        if set(query) - {
            "batch",
            "row",
            "q",
            "mode",
            "intake_status",
            "review_status",
            "page",
            "page_size",
        } or any(len(query.getlist(key)) != 1 for key in query):
            raise ValueError("invalid_query")
        stored = review.load_review_worklist(
            batch_id=query.get("batch"),
            row_id=query.get("row"),
            q=query.get("q", ""),
            mode=query.get("mode", "normalized"),
            intake_status=query.get("intake_status", ""),
            review_status=query.get("review_status", ""),
            page=_positive(query.get("page", "1"), 10000),
            page_size=_positive(query.get("page_size", "20"), 50),
            synthetic_fixtures_only=True,
        )
        timeline = build_audit_timeline(stored)
    except (AuditDataError, guards.SyntheticWriteDenied, DatabaseError):
        return failure(
            request,
            "التدقيق المحفوظ غير متاح. تحقق من إعداد البيئة الاصطناعية المحلية ثم أعد المحاولة.",
            503,
        )
    except (ValueError, TooManyFieldsSent) as exc:
        code = getattr(exc, "status_code", 400)
        if code not in {400, 404, 409, 503}:
            code = 400
        return failure(
            request,
            "معايير غير صالحة أو سجل محفوظ غير متاح. اختر دفعة وسجلًا بهويتيهما الأصليتين.",
            code,
        )
    base = reverse("editorial_workbench:stored")
    params = {
        "q": stored.q,
        "mode": stored.mode,
        "intake_status": stored.intake_status,
        "review_status": stored.review_status,
        "page": stored.page,
        "page_size": stored.page_size,
    }
    if stored.batch_id is not None:
        params["batch"] = str(stored.batch_id)

    def url(values: dict, anchor: str = "") -> str:
        return base + "?" + urlencode(values) + ("#" + anchor if anchor else "")

    response = render(
        request,
        "editorial_workbench/stored.html",
        {
            "stored": stored,
            "timeline": timeline,
            "list_url": base,
            "rows": tuple(
                {"item": row, "url": url({**params, "row": str(row.id)}, "stored-detail")}
                for row in stored.rows
            ),
            "previous_url": url({**params, "page": stored.page - 1}, "stored-records")
            if stored.page > 1
            else None,
            "next_url": url({**params, "page": stored.page + 1}, "stored-records")
            if stored.page < stored.page_count
            else None,
            "pagination_fields": tuple(
                (key, value) for key, value in params.items() if key != "page"
            ),
            "intake_statuses": tuple(c.IntakeStatus),
            "review_statuses": tuple(c.ReviewStatus),
            "return_url": url(params),
        },
    )
    response["Cache-Control"] = "no-store"
    return response
