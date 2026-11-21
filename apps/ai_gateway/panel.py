"""A sibling panel updates source controls only after a separate human selection."""

import uuid
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render as django_render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.guard import denied, private
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service
from apps.precise_citations import editor

from . import services
from .identity import principal

SALT = "ai-citation-panel.v1"
ROUTES = {
    "/casework/ai-citations/": ("POST",),
    "/casework/ai-citations/panel.mjs": ("GET", "HEAD"),
}
STATUSES = {
    "SUCCEEDED": "مواضع مرشحة فقط؛ تحقق بشريًا من صحة النسبة ووجه الاستدلال قبل إضافتها.",
    "PROVIDER_UNAVAILABLE": "لا يوجد مزود مضبوط. يمكنك متابعة الجواب والإحالات اليدوية.",
    "PROVIDER_FAILED": "تعذر تشغيل المزود ضمن مهلة المهمة. بقيت مسودتك ويمكن متابعة الإحالات يدويًا.",
    "OUTPUT_REJECTED": "رُفض خرج المزود لعدم مطابقته للمصدر أو عقد المواضع. بقيت مسودتك دون تعديل.",
    "REVOKED": "أُلغي التشغيل بعد تغير الصلاحية أو إعداد المهمة. لم تُعرض مرشحات.",
}


def token(request, actor, provider, case, *, intent="REQUEST", run_id="", index=None):
    payload = dict(
        case_id=str(case.pk),
        case_ref=case.public_ref,
        revision=case.revision,
        evidence_version=case.evidence_version,
        audience=editor.binding(request, actor, provider, case),
        intent=intent,
    )
    if intent == "REQUEST":
        payload["request_key"] = str(uuid.uuid4())
    else:
        payload.update(run_id=run_id, index=index)
    return signing.dumps(payload, salt=SALT, compress=True)


def render_composer(request, template, context, *args, **kwargs):
    """Exact integration hook for precise_citations.editor.page's render call.

    It never saves, rewrites or submits the composer. Missing configuration leaves
    the original human form usable, with an explicit unavailable panel.
    """
    if (
        template != "precise_citations/editor.html"
        or getattr(settings, "FATWA_AI_GATEWAY_ENABLED", False) is not True
    ):
        return django_render(request, template, context, *args, **kwargs)
    panel = dict(
        state="",
        availability="المهمة أو صلاحية المعالجة غير مضبوطة؛ الإحالات اليدوية متاحة.",
        synthetic=False,
    )
    try:
        _, _, _, spec = services.configuration()
        actor, provider = principal(request)
        case = Case.objects.get(pk=context["selected"]["case_id"])
        panel.update(
            state=token(request, actor, provider, case),
            synthetic=bool(spec and spec.mode == "SYNTHETIC"),
            availability="موفر اختبار اصطناعي؛ ليس دليلًا على جودة Luna العلمية."
            if spec and spec.mode == "SYNTHETIC"
            else (
                "المزود مضبوط؛ جميع الاختيارات تحتاج تحققًا بشريًا."
                if spec
                else STATUSES["PROVIDER_UNAVAILABLE"]
            ),
        )
    except (cases.CaseConflict, IdentityUnavailable, Case.DoesNotExist):
        pass
    panel["choices"] = [item for item in context["choices"] if item["selection"].count(":") == 1]
    response = django_render(
        request, "ai_gateway/composer.html", {**context, "ai_panel": panel}, *args, **kwargs
    )
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; form-action 'self'; img-src 'self'; "
        "media-src 'self'; base-uri 'none'; frame-ancestors 'none'; script-src 'self'; connect-src 'self'"
    )
    return response


def script(request):
    try:
        services.enabled()
        if request.method not in {"GET", "HEAD"} or request.GET:
            return denied("ai_gateway_script_unavailable", 404)
        return private(
            HttpResponse(
                Path(__file__).with_name("panel.mjs").read_text(),
                content_type="text/javascript; charset=utf-8",
            ),
            head=request.method == "HEAD",
        )
    except cases.CaseConflict:
        return denied("ai_gateway_disabled", 404)


def integer(value):
    if type(value) is not str or not value.isascii() or not value.isdecimal() or len(value) > 6:
        raise cases.CaseConflict("ai_gateway_number_invalid")
    return int(value)


@mutation_service
@sensitive_post_parameters("query", "state")
@csrf_protect
def workspace(request):
    try:
        services.enabled()
        action = request.POST.get("action")
        fields = {"action", "state", "csrfmiddlewaretoken"}
        if action == "request":
            fields |= {"query", "selection", "start", "end"}
        if (
            request.method != "POST"
            or action not in {"request", "open", "select"}
            or request.content_type != "application/x-www-form-urlencoded"
            or request.GET
            or request.FILES
            or set(request.POST) != fields
            or any(len(request.POST.getlist(key)) != 1 for key in fields)
        ):
            raise ValueError("form")
        actor, provider = principal(request)
        encoded = request.POST["state"]
        if len(encoded) > 4096:
            raise ValueError("token")
        state = signing.loads(encoded, salt=SALT, max_age=600)
        expected = {"case_id", "case_ref", "revision", "evidence_version", "audience", "intent"}
        expected |= {"request_key"} if action == "request" else {"run_id", "index"}
        if type(state) is not dict or set(state) != expected or state["intent"] != action.upper():
            raise ValueError("state")
        case = Case.objects.filter(
            pk=cases._uuid(state["case_id"]),
            public_ref=state["case_ref"],
            public_ref__in=actor.case_keys,
        ).first()
        if case is None or state["audience"] != editor.binding(request, actor, provider, case):
            raise ValueError("audience")
        cases._versions(case, state["revision"], state["evidence_version"])
        base = dict(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        if action == "request":
            result = services.request_candidates(
                **base,
                query=request.POST["query"],
                selection=request.POST["selection"],
                start=integer(request.POST["start"]),
                end=integer(request.POST["end"]),
                expected_revision=state["revision"],
                expected_evidence_version=state["evidence_version"],
                request_key=state["request_key"],
            )
            run_id, index = result["id"], None
        else:
            run_id, index = state["run_id"], state["index"]
        with services.read_boundary(**base, run_id=run_id, selected_index=index) as result:
            for entry in result["candidates"]:
                entry["open_state"] = token(
                    request,
                    actor,
                    provider,
                    case,
                    intent="OPEN",
                    run_id=run_id,
                    index=entry["index"],
                )
                entry["select_state"] = token(
                    request,
                    actor,
                    provider,
                    case,
                    intent="SELECT",
                    run_id=run_id,
                    index=entry["index"],
                )
            selected = result.get("selected")
            handoff = None
            if action == "select":
                pin = selected["pin"]
                handoff = dict(
                    selection=pin["kind"] + ":" + pin["id"],
                    mode="TEXT",
                    start=pin["locator"]["start"],
                    end=pin["locator"]["end"],
                )
            response = private(
                django_render(
                    request,
                    "ai_gateway/result.html",
                    {
                        "result": result,
                        "message": STATUSES[result["status"]],
                        "opened": selected if action == "open" else None,
                        "handoff": handoff,
                        "next_state": token(request, actor, provider, case),
                    },
                )
            )
            response["X-AI-Citation-Panel"] = "1"
        return response
    except cases.CaseConflict:
        return denied("ai_gateway_unavailable_or_stale", 409)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except (signing.BadSignature, ValueError, TypeError, KeyError, SuspiciousOperation):
        return denied("ai_gateway_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("ai_gateway_store_unavailable", 503)
