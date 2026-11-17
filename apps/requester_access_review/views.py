from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.casework import services as cases
from apps.casework_web import requester_workspace as workspace
from apps.casework_web import views as case_views
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, require_provider

from . import services


DELIVERY_LABELS = {
    "CURRENT_APPROVAL_REQUIRED": "ينتظر الجواب اعتمادًا مطابقًا للوقائع الحالية",
    "NOT_STAGED": "الجواب المعتمد لم يُجهز للتسليم بعد",
    "EVIDENCE_UNAVAILABLE": "لا يتوفر تحقق موثوق من إثبات التسليم حاليًا",
    "NOT_FULLY_DELIVERED": "لم تثبت القناة تسليم جميع أجزاء الجواب",
    "NEEDS_RECONCILIATION": "حالة تسليم الجواب تحتاج إلى مراجعة",
    "PROVIDER_EVIDENCE_INCOMPLETE": "أبلغت القناة عن التسليم، لكن الإثبات الموقّع غير مكتمل",
    "PROVIDER_REPORTED_DELIVERY_VERIFIED": "تحققت إيصالات المزود الموقّعة لجميع أجزاء الجواب",
}

@sensitive_post_parameters("token", "text")
@sensitive_variables("token")
@csrf_protect
def requester(request):
    if request.method == "POST" and request.POST.get("action") != "request_access_review":
        return workspace.workspace(request)
    try:
        token = workspace._capability(request)
        snapshot = services.requester_snapshot(
            token,
            verifier=getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None),
            synthetic_fixtures_only=True,
        )
        result = snapshot["case"]
        if request.method == "POST":
            fields = workspace._form(request, {"action", "reason", "review_proof"})
            if fields["reason"] not in services.REASONS:
                return denied("access_review_reason_invalid", 400)
            proof = workspace._binding(request, token, "access-review:" + result["public_ref"])
            if (workspace.HEX.fullmatch(fields["review_proof"]) is None
                    or not compare_digest(proof, fields["review_proof"])):
                return denied("access_review_form_changed", 409)
            services.request_review(token=token, reason=fields["reason"],
                                    expected_case_ref=result["public_ref"], synthetic_fixtures_only=True)
            return private(HttpResponse(status=303, headers={"Location": workspace.URL}))
        get_token(request)
        return private(render(request, "requester_access_review/requester.html", {
            "result": result, "status_label": workspace.LABELS.get(result["status"], "قيد المراجعة"),
            "form_proof": workspace._binding(
                request, token, f"followup:{result['public_ref']}:{result['revision']}"),
            "review_proof": workspace._binding(request, token, "access-review:" + result["public_ref"]),
            "access_reviews": snapshot["reviews"],
            "delivery_label": DELIVERY_LABELS.get(
                result.get("delivery_status"), "حالة التسليم غير محسومة"
            ),
        }))
    except (workspace.InvalidForm, SuspiciousOperation):
        return denied("access_review_form_invalid", 400)
    except cases.CaseConflict:
        return workspace._locked(request, "يلزم وصول صالح لطلب مراجعة الرمز. عند فقدان الوصول بالكامل استخدم مسار التحقق الموثوق.",
                                 404 if request.method == "POST" else 200)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@csrf_protect
def staff(request):
    if request.method == "POST" and request.POST.get("action") not in {"access_acknowledge", "access_close", "access_queue"}:
        return case_views.staff(request)
    try:
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        require_provider(provider)
        provider_id = provider.provider_id
        identity = current_staff(request, provider)
        provider = RequestDirectory(provider, identity, authenticated_provider_id=provider_id)
        common = {"subject_id": identity.subject_id, "provider": provider, "synthetic_fixtures_only": True}
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "access_queue":
                case_views._form(request, {"action"})
            else:
                fields = case_views._form(request, {"action", "review_id", "revision"})
                services.advance_review(**common, review_id=fields["review_id"],
                                        expected_revision=case_views._integer(fields["revision"]),
                                        action="acknowledge" if action == "access_acknowledge" else "close")
                return private(HttpResponse(status=303, headers={"Location": "/casework/staff/"}))
        rows = services.staff_queue(**common)
        get_token(request)
        return private(render(request, "requester_access_review/staff.html", {
            "reviews": rows, "cases": cases.list_cases(**common),
        }))
    except (case_views.InvalidForm, SuspiciousOperation):
        return denied("access_review_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("access_review_update_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
