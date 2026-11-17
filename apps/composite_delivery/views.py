"""Native CSRF-protected delivery controls; trusted identity/verifiers are server-only."""

import json

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue import services as queue
from apps.delivery_queue.author_handoff import InvalidSignedResponse
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import desk as control
from . import services

ACTIONS = {
    "composite_open",
    "composite_export",
    "composite_stage",
    "composite_reconcile",
    "composite_receipt",
}


def _page(request, *, code=200, **context):
    # A denial page carries no case data. Do not re-enter the scoped frame's
    # failing identity lookup while rendering the original denial.
    request._mufti_workspace_error = code >= 400
    get_token(request)
    return private(render(request, "composite_delivery/control.html", context, status=code))


@sensitive_post_parameters("response_json")
@csrf_protect
def desk(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("invalid_composite_action")
        action = request.POST["action"]
        required = {"action", "case_ref"}
        if action != "composite_open":
            required |= {"revision", "evidence_version", "plan_sha256"}
        if action in {"composite_stage", "composite_receipt", "composite_reconcile"}:
            required.add("confirm")
        if action in {"composite_stage", "composite_receipt"}:
            required.add("response_json")
        if action == "composite_receipt":
            required.add("part_id")
        values = _form(request, required)
        if request.FILES:
            raise InvalidForm("unexpected_upload")
        directory = _provider()
        identity = current_staff(request, directory, case_key=values["case_ref"])
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next(
            (c for c in cases.list_cases(**common) if c["public_ref"] == values["case_ref"]), None
        )
        if selected is None:
            return _page(request, code=404, error="القضية غير متاحة لهذا المكتب.")
        common["case_id"] = selected["case_id"]
        notice = ""
        if action != "composite_open":
            if "confirm" in required and values["confirm"] != "yes":
                raise InvalidForm("confirmation_required")
            result = control.apply_desk_action(
                **common,
                action=action,
                revision=_integer(values["revision"]),
                evidence_version=_integer(values["evidence_version"]),
                plan_sha256=values["plan_sha256"],
                response_json=values.get("response_json", ""),
                part_id=values.get("part_id", ""),
            )
            if action == "composite_export":
                response = HttpResponse(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    content_type="application/json; charset=utf-8",
                )
                response["Content-Disposition"] = (
                    'attachment; filename="synthetic-composite-plan.json"'
                )
                return private(response)
            notice = result
        return _page(request, desk=control.read_delivery_desk(**common), notice=notice)
    except IdentityUnavailable:
        return _page(request, code=403, error="يلزم دخول المفتي المخوّل ونطاق القضية الحالي.")
    except (InvalidForm, InvalidSignedResponse, SuspiciousOperation):
        return _page(
            request, code=400, error="لم يُقبل النموذج. أعد فتح المكتب وتحقق من الحقول والإيصال."
        )
    except (cases.CaseConflict, queue.QueueConflict, ValueError):
        return _page(
            request,
            code=409,
            error="توقف الإجراء: تغيّر السياق أو لم يثبت تطابق الإيصال. أعد فتح القضية؛ لم يحدث إرسال أو إعادة محاولة.",
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _page(
            request,
            code=503,
            error="تعذر التحقق من السجل التجريبي. لم يثبت تنفيذ الإجراء؛ أعد فتح الحالة للتحقق.",
        )


def dispatch(request):
    """Owned test/demo URL composition; integrator can dispatch ACTIONS directly."""
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return desk(request)
    from apps.requester_team_journey.views import staff

    return staff(request)
