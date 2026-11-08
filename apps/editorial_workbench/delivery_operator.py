"""Read-only local delivery review plus explicit operator-only quarantine."""
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.delivery_planner.outbox import OutboxConflict
from apps.delivery_planner.outbox_recovery import (
    flag_expired_reservations, reconciliation_queue,
)

from .reviewer_access import signed_in
from .views import _source_journal_directory


@require_http_methods(["GET", "HEAD", "POST"])
def operator_outbox(request):
    """Show what needs human follow-up; no send, retry, or delivery approval."""
    template = "editorial_workbench/delivery_operator.html"
    if not signed_in(request, "operator"):
        if request.method in {"GET", "HEAD"}:
            return redirect("operator_login")
        return render(
            request,
            "editorial_workbench/reviewer_login.html",
            {"operator_login": True, "message": "يلزم تسجيل الدخول بهوية مشغّل التسليم."},
            status=403,
        )

    def fail(message, status):
        return render(request, template, {"message": message}, status=status)

    if request.META.get("QUERY_STRING"):
        return fail("افتح قائمة التسليم دون معاملات إضافية.", 400)
    directory = _source_journal_directory()
    if directory is None:
        return fail("لم يُضبط مجلد التدريب المحلي.", 503)

    if request.method == "POST":
        if request.content_type != "application/x-www-form-urlencoded":
            return fail("استخدم النموذج المعروض لإجراء المصالحة.", 415)
        try:
            fields = request.POST
            if (
                set(fields) - {"csrfmiddlewaretoken"} != {"action"}
                or fields.get("action") != "flag_expired"
                or any(len(fields.getlist(key)) != 1 for key in fields)
            ):
                return fail("طلب إجراء غير معرّف.", 400)
        except SuspiciousOperation:
            return fail("تعذّرت قراءة النموذج.", 400)
        try:
            flag_expired_reservations(
                directory,
                operator_id="synthetic-operator",
                verify_operator=lambda actor: (
                    actor == "synthetic-operator" and signed_in(request, "operator")
                ),
                synthetic_fixtures_only=True,
            )
        except (OutboxConflict, OSError):
            return fail("تعذّرت مراجعة الحجوزات المنتهية.", 503)
        return HttpResponse(status=303, headers={"Location": reverse("operator_outbox")})

    try:
        items = reconciliation_queue(directory, synthetic_fixtures_only=True)
    except (OutboxConflict, OSError):
        return fail("تعذّرت قراءة سجل التسليم المحفوظ.", 503)

    return render(request, template, {"items": items})
