"""Native CSRF-bound human verification and preview-confirmed corrections."""

import uuid

from django.core import signing
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import services
from .boundary import digest, scope

ACTIONS = frozenset(
    {
        "ir_open",
        "ir_capture",
        "ir_person",
        "ir_propose",
        "ir_decide",
        "ir_prepare",
        "ir_apply",
        "ir_history",
    }
)
FIELDS = {
    "action",
    "case_ref",
    "csrfmiddlewaretoken",
    "state",
    "query",
    "label",
    "reason",
    "evidence",
    "identity_id",
    "person_id",
    "proposal_id",
    "kind",
    "source_person_id",
    "target_person_id",
    "identity_ids",
    "preview",
    "confirmed",
}


def _audience(request, actor, provider, case_id):
    get_token(request)
    return digest(
        [
            str(case_id),
            provider.provider_id,
            actor.subject_id,
            actor.auth_epoch,
            request.META.get("CSRF_COOKIE", ""),
        ]
    )


def _token(value, audience, salt):
    return signing.dumps({"value": value, "audience": audience}, salt=salt, compress=True)


def _open(value, audience, salt):
    if type(value) is not str or not value or len(value) > 32000:
        raise cases.CaseConflict("identity_registry_form_invalid")
    try:
        data = signing.loads(value, salt=salt, max_age=600)
    except signing.BadSignature as exc:
        raise cases.CaseConflict("identity_registry_form_expired") from exc
    if data.get("audience") != audience or type(data.get("value")) is not dict:
        raise cases.CaseConflict("identity_registry_form_audience")
    return data["value"]


def page(request, base, actor, provider, *, query="", preview=None, message=""):
    with scope(**base) as guard:
        result = services.desk_locked(guard, case_id=base["case_id"], query=query)
        audience = _audience(request, actor, provider, base["case_id"])
        state = {
            "expected_snapshot": result["snapshot"],
            "expected_revision": result["revision"],
            "expected_evidence_version": result["evidence_version"],
            "request_key": str(uuid.uuid4()),
        }
        return private(
            render(
                request,
                "identity_registry/desk.html",
                {
                    "result": result,
                    "message": message,
                    "state": _token(state, audience, "identity-registry-state.v1"),
                    "preview": preview,
                    "preview_token": _token(preview, audience, "identity-registry-preview.v1")
                    if preview
                    else "",
                },
            )
        )


@mutation_service
@sensitive_post_parameters("label", "reason", "evidence", "state", "preview")
@csrf_protect
def workspace(request):
    try:
        if (
            request.method != "POST"
            or request.POST.get("action") not in ACTIONS
            or request.FILES
            or set(request.POST) - FIELDS
        ):
            raise InvalidForm("identity_registry_form_invalid")
        if (
            any(len(values) != 1 for key, values in request.POST.lists() if key != "identity_ids")
            or len(request.POST.getlist("identity_ids")) > services.MAX_IDENTITIES
        ):
            raise InvalidForm("identity_registry_form_invalid")
        directory = _provider()
        actor = current_staff(request, directory)
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        case = Case.objects.filter(
            public_ref=request.POST.get("case_ref"), public_ref__in=actor.case_keys
        ).first()
        if case is None:
            return denied("identity_registry_unavailable", 404)
        base = dict(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        action = request.POST["action"]
        with synthetic_queue_atomic():
            if action in {"ir_open", "ir_history"}:
                return page(request, base, actor, provider, query=request.POST.get("query", ""))
            audience = _audience(request, actor, provider, case.pk)
            state = _open(request.POST.get("state"), audience, "identity-registry-state.v1")
            common = {**base, **state}
            confirmed = request.POST.get("confirmed") == "yes"
            if action == "ir_capture":
                services.capture(**common)
            elif action == "ir_person":
                services.create_person(
                    **common,
                    label=request.POST.get("label", ""),
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            elif action == "ir_propose":
                services.propose(
                    **common,
                    identity_id=request.POST.get("identity_id"),
                    person_id=request.POST.get("person_id"),
                    evidence=request.POST.get("evidence", ""),
                    confirmed=confirmed,
                )
            elif action == "ir_decide":
                services.decide(
                    **common,
                    identity_id=request.POST.get("identity_id"),
                    proposal_id=request.POST.get("proposal_id"),
                    kind=request.POST.get("kind"),
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            elif action == "ir_prepare":
                preview = services.prepare(
                    **base,
                    kind=request.POST.get("kind"),
                    source_person_id=request.POST.get("source_person_id"),
                    target_person_id=request.POST.get("target_person_id"),
                    identity_ids=request.POST.getlist("identity_ids"),
                )
                if preview["snapshot"] != state["expected_snapshot"]:
                    raise cases.CaseConflict("identity_registry_version_changed")
                return page(request, base, actor, provider, preview=preview)
            else:
                preview = _open(
                    request.POST.get("preview"), audience, "identity-registry-preview.v1"
                )
                services.apply(
                    **common,
                    preview=preview,
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            return page(
                request,
                base,
                actor,
                provider,
                message="حُفظ إجراء الهوية مع أثره وسنده؛ بقيت القضايا ومصادرها ووجهات الرد كما هي.",
            )
    except (
        cases.CaseConflict,
        IdentityUnavailable,
        InvalidForm,
        SyntheticWriteDenied,
        DatabaseError,
        ValueError,
        KeyError,
    ):
        return denied("identity_registry_action_unavailable", 409)
