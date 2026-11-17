from hmac import compare_digest
import re
import secrets

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
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, require_provider

from . import recovery, services


DELIVERY_LABELS = {
    "CURRENT_APPROVAL_REQUIRED": "ينتظر الجواب اعتمادًا مطابقًا للوقائع الحالية",
    "NOT_STAGED": "الجواب المعتمد لم يُجهز للتسليم بعد",
    "EVIDENCE_UNAVAILABLE": "لا يتوفر تحقق موثوق من إثبات التسليم حاليًا",
    "NOT_FULLY_DELIVERED": "لم تثبت القناة تسليم جميع أجزاء الجواب",
    "NEEDS_RECONCILIATION": "حالة تسليم الجواب تحتاج إلى مراجعة",
    "PROVIDER_EVIDENCE_INCOMPLETE": "أبلغت القناة عن التسليم، لكن الإثبات الموقّع غير مكتمل",
    "PROVIDER_REPORTED_DELIVERY_VERIFIED": "تحققت إيصالات المزود الموقّعة لجميع أجزاء الجواب",
}

def _recovery_context(request):
    nonce = secrets.token_hex(16)
    return {
        "recovery_nonce": nonce,
        "recovery_proof": browser_proof(request, "casework.trusted-recovery.v1", nonce),
        "recovery_enabled": isinstance(
            getattr(settings, "FATWA_CASEWORK_RECOVERY_AUTHORITY", None),
            recovery.TrustedRecoveryAuthority,
        ),
    }


def _recovery_page(request, *, message="", status=200, issued_token=None):
    get_token(request)
    return private(render(request, "requester_access_review/requester.html", {
        "result": None, "message": message,
        "issued_recovery_token": issued_token,
        **_recovery_context(request),
    }, status=status))


@sensitive_variables("fields", "result")
def _recover(request):
    try:
        fields = workspace._form(
            request, {"action", "public_ref", "credential", "recovery_nonce", "recovery_proof"}
        )
        nonce = fields["recovery_nonce"]
        if (
            fields["action"] != "trusted_recover"
            or re.fullmatch(r"[a-f0-9]{32}", nonce) is None
            or re.fullmatch(r"[a-f0-9]{64}", fields["recovery_proof"]) is None
            or not compare_digest(
                fields["recovery_proof"],
                browser_proof(request, "casework.trusted-recovery.v1", nonce),
            )
        ):
            return _recovery_page(
                request, message="لم تُقبل الاستعادة. أعد فتح النموذج ثم حاول مجددًا.",
                status=404,
            )
        result = recovery.recover_lost_access(
            public_ref=fields["public_ref"],
            credential=fields["credential"],
            authority=getattr(settings, "FATWA_CASEWORK_RECOVERY_AUTHORITY", None),
            synthetic_fixtures_only=True,
        )
        response = _recovery_page(
            request,
            message="تحقق مزود الهوية الموثوق وأُبطل الوصول السابق. احفظ الرمز الجديد.",
            issued_token=result["token"],
        )
        return private(workspace.remember(request, response, result["token"]))
    except (workspace.InvalidForm, SuspiciousOperation, cases.CaseConflict):
        return _recovery_page(
            request, message="تعذرت الاستعادة. رقم القضية وحده لا يثبت ملكيتها.",
            status=404,
        )
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@sensitive_post_parameters("token", "text", "credential", "recovery_proof")
@sensitive_variables("token")
@csrf_protect
def requester(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "trusted_recover":
            return _recover(request)
        if action != "request_access_review":
            return workspace.workspace(request)
    try:
        token = workspace._capability(request)
        snapshot = services.requester_snapshot(
            token,
            verifier=getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None),
            show_approved_answer=getattr(
                settings, "FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED", False
            ) is True,
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
            "private_answer": snapshot["private_answer"],
            "delivery_label": DELIVERY_LABELS.get(
                result.get("delivery_status"), "حالة التسليم غير محسومة"
            ),
            **_recovery_context(request),
        }))
    except (workspace.InvalidForm, SuspiciousOperation):
        return denied("access_review_form_invalid", 400)
    except cases.CaseConflict:
        return _recovery_page(
            request,
            message="يلزم وصول صالح للمتابعة. عند فقدانه يمكنك استخدام إثبات تحقق خارجي موثوق إذا كانت الخدمة مفعلة.",
            status=404 if request.method == "POST" else 200,
        )
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
