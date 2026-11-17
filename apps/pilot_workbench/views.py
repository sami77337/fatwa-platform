"""Native human-confirmed local fixture forms; no arbitrary signing payload or key input."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue import services as queue
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = frozenset({"pilot_open", "pilot_authorize", "pilot_report"})


def _page(request, *, code=200, **context):
    request._mufti_workspace_error = code >= 400
    get_token(request)
    return private(render(request, "pilot_workbench/desk.html", context, status=code))


@csrf_protect
def desk(request):
    try:
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("pilot_action_invalid")
        action = request.POST["action"]
        required = {"action", "case_ref"}
        if action != "pilot_open":
            required |= {"revision", "evidence_version", "plan_sha256", "confirm"}
        if action == "pilot_report":
            required |= {"part_id", "expected_state", "outcome"}
        values = _form(request, required)
        if request.FILES:
            raise InvalidForm("pilot_upload_not_allowed")
        directory = _provider()
        actor = current_staff(request, directory, case_key=values["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected = next(
            (c for c in cases.list_cases(**common) if c["public_ref"] == values["case_ref"]), None
        )
        if selected is None:
            return _page(request, code=404, error="القضية غير متاحة لهذا المشغّل التجريبي.")
        common["case_id"] = selected["case_id"]
        notice = ""
        if action != "pilot_open":
            if values["confirm"] != "yes":
                raise InvalidForm("pilot_confirmation_required")
            notice = services.apply_action(
                **common,
                action=action,
                revision=_integer(values["revision"]),
                evidence_version=_integer(values["evidence_version"]),
                plan_sha256=values["plan_sha256"],
                confirmed=True,
                part_id=values.get("part_id", ""),
                expected_state=values.get("expected_state", ""),
                outcome=values.get("outcome", ""),
            )
        return _page(request, desk=services.read_workbench(**common), notice=notice)
    except IdentityUnavailable:
        return _page(request, code=403, error="يلزم دخول المفتي المخوّل ونطاق القضية الحالي.")
    except (InvalidForm, SuspiciousOperation):
        return _page(request, code=400, error="النموذج غير صالح؛ افتح اللوحة مجددًا وراجع التأكيد.")
    except (cases.CaseConflict, queue.QueueConflict, ValueError):
        return _page(
            request,
            code=409,
            error="توقف الإجراء التجريبي: الصلاحية أو النسخة أو حالة الجزء غير متاحة. أعد فتح اللوحة؛ لا إعادة محاولة تلقائية.",
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _page(
            request, code=503, error="تعذر التحقق من السجل التجريبي. افحص الحالة قبل أي إجراء جديد."
        )


def dispatch(request):
    """Local test composition; root imports ACTIONS/desk into its staff dispatcher."""
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return desk(request)
    from apps.requester_team_journey.views import staff

    return staff(request)
