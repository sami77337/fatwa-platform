"""Native Arabic staff journey over the existing case-delivery services."""

import json
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import delivery, delivery_reconciliation, services
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider, staff_login
from apps.delivery_planner.planner import InvalidPlan
from apps.delivery_queue import services as queue
from apps.delivery_queue.author_handoff import InvalidSignedResponse, decode_signed_response
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity

LABELS = {
    "RECEIVED": "تم استلام السؤال",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "بانتظار استيضاح",
    "RETURNED_FOR_CHANGES": "أعيد للتعديل",
    "ANSWERED": "اعتمد المفتي الجواب",
    "STAGED": "مجهز ولم يُرسل",
    "LEASED": "محجوز لمحاولة التسليم",
    "SENT_UNCONFIRMED": "قبله المزود ولم يؤكد التسليم",
    "DELIVERED": "أبلغ المزود بالتسليم",
    "UNKNOWN_REQUIRES_RECONCILIATION": "نتيجة المحاولة غير محسومة",
    "FAILED_REQUIRES_REVIEW": "أبلغ المزود بفشل المحاولة",
    "VERIFIED_PROVIDER_REPORT": "إثبات المزود الموقّع متحقق",
    "UNVERIFIED": "لا يوجد إثبات موقّع متحقق",
    "VERIFIER_UNAVAILABLE": "التحقق من الإثبات غير متاح",
    "NOT_REPORTED_DELIVERED": "لا يوجد إعلان تسليم",
    "TRUSTED_RESERVATION_REQUIRED": "بانتظار العامل المخوّل",
    "NEW_MUFTI_REVIEW_REQUIRED": "يلزم مسار مراجعة جديد من المفتي",
    "AWAIT_PROVIDER_OUTCOME": "انتظار نتيجة المزود",
    "QUARANTINE_EXPIRED_ATTEMPT": "انتهت المهلة؛ سجّل المحاولة كغير محسومة",
    "REVIEW_PROVIDER_OUTCOME_NO_RETRY": "راجع نتيجة المزود؛ لا إعادة إرسال تلقائية",
    "CHECK_SIGNED_EVIDENCE": "تحقق من الإثبات الموقّع",
    "NO_ACTION": "لا إجراء مطلوب لهذا الجزء",
}


def _page(request, *, status=200, **context):
    get_token(request)
    return private(render(request, "case_delivery_desk/desk.html", context, status=status))


def _error(request, message, status):
    return _page(request, error=message, status=status)


def _request(common, max_chars, split):
    result = delivery.prepare_case_delivery(**common, max_chars=max_chars, split=split)
    digest = sha256(queue._canonical(result)).hexdigest()
    return {**result, "request_sha256": digest}


def _report(common):
    try:
        report = delivery_reconciliation.read_case_delivery_followup(
            **common,
            verifier=getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None),
        )
    except services.CaseConflict as exc:
        if str(exc) == "case_delivery_not_staged":
            return None
        raise
    return {
        **report,
        "parts": [
            {
                **part,
                "state_label": LABELS[part["state"]],
                "evidence_label": LABELS[part["provider_evidence"]],
                "action_label": LABELS[part["next_action"]],
            }
            for part in report["parts"]
        ],
    }


@sensitive_post_parameters("credential")
@csrf_protect
def login(request):
    if request.method == "POST":
        response = staff_login(request)
        if response.status_code != 303:
            return _error(
                request,
                "تعذر تسجيل الدخول. تحقق من الهوية التجريبية وصلاحيتها.",
                response.status_code,
            )
        return response
    get_token(request)
    return private(render(request, "case_delivery_desk/login.html"))


@sensitive_post_parameters("response_json")
@csrf_protect
def desk(request):
    try:
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        rows = services.list_cases(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        cases = [
            {"public_ref": row["public_ref"], "status_label": LABELS[row["status"]]} for row in rows
        ]
        if request.method in ("GET", "HEAD"):
            return _page(request, cases=cases, authenticated=True)
        action = request.POST.get("action", "")
        required = {"action", "case_ref"}
        if action in ("prepare", "export", "stage"):
            required |= {"max_chars", "split"}
            if action == "stage":
                required |= {"response_json"}
        elif action == "quarantine":
            required |= {"plan_sha256", "confirmation"}
        elif action != "open":
            raise InvalidForm("unknown_action")
        fields = _form(request, required)
        validate_identity(identity, case_key=fields["case_ref"])
        selected = next((row for row in rows if row["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            raise IdentityUnavailable("case_not_available")
        common = dict(
            case_id=selected["case_id"],
            subject_id=identity.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        options, prepared, notice = {"max_chars": 6000, "split": False}, None, None
        if action in ("prepare", "export", "stage"):
            if fields["split"] not in ("yes", "no"):
                raise InvalidForm("invalid_split")
            options = {
                "max_chars": _integer(fields["max_chars"]),
                "split": fields["split"] == "yes",
            }
            prepared = _request(common, **options)
            if action == "export":
                response = HttpResponse(
                    json.dumps(prepared, ensure_ascii=False, indent=2),
                    content_type="application/json; charset=utf-8",
                )
                response["Content-Disposition"] = (
                    'attachment; filename="synthetic-return-request.json"'
                )
                return private(response)
            if action == "stage":
                requested_digest, receipt = decode_signed_response(fields["response_json"])
                if not compare_digest(requested_digest, prepared["request_sha256"]):
                    raise services.CaseConflict("return_request_changed")
                result = delivery.stage_case_delivery(
                    **common,
                    **options,
                    receipt=receipt,
                    verify_receipt=getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None),
                )
                notice = (
                    "حُفظت الخطة المعتمدة في الطابور. هذا الإجراء لم يرسل الجواب."
                    if result["status"] == "STAGED_NOT_SENT"
                    else "هذه الخطة مسجلة سابقًا؛ لم تُنشأ محاولة إضافية."
                )
                prepared = None
        elif action == "quarantine":
            if fields["confirmation"] != "quarantine-expired-only":
                raise InvalidForm("explicit_confirmation_required")
            result = delivery_reconciliation.quarantine_case_delivery(
                **common,
                expected_plan_sha256=fields["plan_sha256"],
                verifier=getattr(settings, "FATWA_CASE_DELIVERY_PROVIDER_VERIFIER", None),
            )
            notice = f"سُجّل {result['quarantined_parts']} من الحجوزات المنتهية كمحاولات غير محسومة. لم تحدث إعادة إرسال."
        # A fresh read prevents a stale selection from rendering old approval text.
        selected = services.read_case(**common)
        approved = next(
            (a for a in selected["answers"] if a["id"] == selected["approved_answer_id"]), None
        )
        report = _report(common) if approved else None
        return _page(
            request,
            cases=cases,
            authenticated=True,
            selected={
                "public_ref": selected["public_ref"],
                "status_label": LABELS[selected["status"]],
            },
            approved=approved,
            report=report,
            prepared=prepared,
            options=options,
            notice=notice,
        )
    except IdentityUnavailable:
        return _error(request, "يلزم دخول المفتي المخوّل لهذه القضية. سجّل الدخول مجددًا.", 403)
    except (InvalidForm, InvalidSignedResponse, SuspiciousOperation):
        return _error(request, "لم يُقبل النموذج. تحقق من الحقول وصيغة الرد الموقّع.", 400)
    except (services.CaseConflict, queue.QueueConflict, InvalidPlan):
        return _error(
            request,
            "لم يُقبل الإجراء. أعد فتح القضية وتحقق من الاعتماد والخطة والتوقيع الحالي.",
            409,
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _error(request, "تعذر الوصول إلى السجل التجريبي. حاول لاحقًا.", 503)


def stylesheet(request):
    return private(
        HttpResponse(
            Path(__file__).with_name("desk.css").read_text(), content_type="text/css; charset=utf-8"
        )
    )
