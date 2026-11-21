"""Native exact preview/confirmation, current sessions, CSRF and source-free audit."""

import uuid
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web import access
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.operational_workspace import access as operational_access
from apps.operational_workspace import identity

from . import catalog, services

STAFF_PATH = "/casework/staff/derived-data/"
OPERATIONAL_PATH = "/casework/operations/derived-data/"


def _common(request):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if request.path == OPERATIONAL_PATH:
        actor, until = operational_access.current(request, directory)
        provider = identity.RequestDirectory(directory, actor)
    elif request.path == STAFF_PATH:
        actor = access.current_staff(request, directory)
        until = actor.valid_until
        provider = access.RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
    else:
        raise InvalidForm("derived_path_invalid")
    return dict(
        provider=provider,
        subject_id=actor.subject_id,
        session_deadline=until,
        synthetic_fixtures_only=True,
    )


def _fields(request):
    if request.GET or request.FILES or request.method not in {"GET", "POST"}:
        raise InvalidForm("derived_form_invalid")
    if request.method == "GET":
        return {"action": "dm_open"}
    action = request.POST.get("action")
    fields = {"action"}
    if action == "dm_inspect":
        fields |= {"kind", "identifier"}
    elif action == "dm_preview":
        fields |= {
            "operation",
            "kind",
            "identifier",
            "header_digest",
            "payload_digest",
            "clearance",
            "watermark",
            "reason",
            "request_key",
            "fragment",
        }
    elif action == "dm_apply":
        fields |= {"plan", "proof", "confirmed"}
    elif action != "dm_open":
        raise InvalidForm("derived_form_invalid")
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or set(request.POST) != fields | {"csrfmiddlewaretoken"}
        or any(len(value) != 1 for _, value in request.POST.lists())
    ):
        raise InvalidForm("derived_form_invalid")
    return {key: request.POST[key] for key in fields}


def _proof(request, base, plan):
    return browser_proof(
        request,
        "fatwa.derived-preview.v1",
        catalog.digest([request.path, base["provider"].provider_id, base["subject_id"], plan]),
    )


@sensitive_post_parameters("reason", "fragment", "plan")
@csrf_protect
def workspace(request):
    try:
        fields, base = _fields(request), _common(request)
        if fields["action"] == "dm_open":
            with services.desk(**base) as result:
                return private(
                    render(
                        request,
                        "derived_maintenance/desk.html",
                        {"result": result, "request_key": str(uuid.uuid4())},
                    )
                )
        if fields["action"] == "dm_inspect":
            with services.inspect(
                kind=fields["kind"], identifier=fields["identifier"], **base
            ) as result:
                return private(
                    render(
                        request,
                        "derived_maintenance/item.html",
                        {**result, "request_key": str(uuid.uuid4())},
                    )
                )
        if fields["action"] == "dm_preview":
            proposal = {
                name: value
                for name, value in fields.items()
                if name not in {"operation", "action", "fragment"}
            }
            proposal["action"] = fields["operation"]
            if proposal["action"] == "REBUILD" and proposal["kind"] == "AI_CANDIDATES":
                proposal["parameters"] = {"query": fields["fragment"]}
            else:
                if fields["fragment"]:
                    raise InvalidForm("derived_unexpected_fragment")
                proposal["parameters"] = {}
            with services.preview(proposal=proposal, **base) as plan:
                return private(
                    render(
                        request,
                        "derived_maintenance/preview.html",
                        {
                            "plan": plan,
                            "serialized": catalog.canonical(plan),
                            "proof": _proof(request, base, plan),
                        },
                    )
                )
        plan = services.decode(fields["plan"])
        if fields["confirmed"] != "yes" or not compare_digest(
            fields["proof"], _proof(request, base, plan)
        ):
            raise InvalidForm("derived_preview_invalid")
        with services.apply(plan=plan, confirmed=True, **base) as result:
            if result.get("status") == "SUCCEEDED" and request.path == STAFF_PATH:
                resource = plan["resources"][0]
                if resource["kind"] == "AI_CANDIDATES":
                    from apps.ai_gateway import services as gateway
                    from apps.ai_gateway.identity import principal
                    from apps.casework.models import Case

                    actor, provider = principal(request)
                    case = Case.objects.get(pk=resource["case_id"])
                    with gateway.read_boundary(
                        case_id=str(case.pk),
                        subject_id=actor.subject_id,
                        provider=provider,
                        synthetic_fixtures_only=True,
                        run_id=result["child_id"],
                    ) as candidates:
                        return private(
                            render(
                                request,
                                "derived_maintenance/saved.html",
                                {
                                    "result": result,
                                    "candidates": candidates,
                                    "citation_case_ref": case.public_ref,
                                },
                            )
                        )
                return private(
                    render(
                        request,
                        "derived_maintenance/saved.html",
                        {"result": result, "search_case_ref": resource["case_ref"]},
                    )
                )
            return private(render(request, "derived_maintenance/saved.html", {"result": result}))
    except IdentityUnavailable:
        return denied("derived_current_session_required", 403)
    except cases.CaseConflict:
        return denied("derived_change_unavailable", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError, KeyError):
        return denied("derived_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("derived_store_unavailable", 503)
